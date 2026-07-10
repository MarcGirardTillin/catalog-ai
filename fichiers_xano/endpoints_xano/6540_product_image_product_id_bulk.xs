// Bulk add product_image records to a product from two sources:
//   1. A list of external image URLs (downloaded into Xano storage), and
//   2. Directly-uploaded files (raw bytes stored as-is, pattern from 584).
// Each image is imported into Xano storage; the resulting Xano URL is stored in `src`.
// Both inputs are optional so the caller can provide either one, the other, or both.
query "product_image/{product_id}/bulk" verb=POST {
  api_group = "Tillin API endpoints"
  auth = "user"

  input {
    int product_id {
      table = "product"
    }

    text[]? image_urls? filters=trim
    file[]? files?
  }

  stack {
    // 1. Fetch product and user
    db.get product {
      field_name = "id"
      field_value = $input.product_id
    } as $product
  
    db.get user {
      field_name = "id"
      field_value = $auth.id
      output = ["id", "company"]
    } as $user
  
    // 2. Multi-tenant security check
    precondition ($product != null && $user.company == $product.company_id) {
      error_type = "notfound"
      error = "Product not found"
    }
  
    // 3. Determine the starting position from existing active images
    db.query product_image {
      where = $db.product_image.product_id == $input.product_id && $db.product_image.active == true
      sort = {product_image.position: "desc"}
      return = {type: "single"}
    } as $last_image
  
    var $next_position {
      value = 1
    }
  
    conditional {
      if ($last_image != null && $last_image.position != null) {
        var.update $next_position {
          value = $last_image.position + 1
        }
      }
    }
  
    var $created_images {
      value = []
    }
  
    // 4. Import one image into Xano storage per non-empty URL, then create the record
    foreach ($input.image_urls ?? []) {
      each as $image_url {
        conditional {
          if ($image_url != null && ($image_url|strlen) > 0) {
            // 4a. Normalize the URL to ensure it has a proper protocol
            var $normalized_url {
              value = $image_url
            }
          
            conditional {
              if ($normalized_url|starts_with:"//") {
                var.update $normalized_url {
                  value = "https:" ~ $normalized_url
                }
              }
            
              elseif (($normalized_url|starts_with:"http") == false) {
                var.update $normalized_url {
                  value = "https://" ~ $normalized_url
                }
              }
            }
          
            // 4b. Build a slugified filename from the product title + position
            var $slug {
              value = ($product.title ?? "image")|to_lower|replace:" ":"-"
            }
          
            var $clean_slug {
              value = "/[^a-z0-9-]/"|regex_replace:"":$slug
            }
          
            // Extract the extension from the source URL, ignoring query params
            var $extension_match {
              value = "/\\.([a-z0-9]+)(?:\\?|#|$)/i"|regex_get_first_match:$image_url
            }
          
            var $final_ext {
              value = "." ~ ($extension_match|get:1 ?? "jpg")
            }
          
            var $new_filename {
              value = $clean_slug ~ "-" ~ ($next_position|to_text) ~ $final_ext
            }
          
            // 4c. Import into Xano storage and create the record.
            // Wrapped in try_catch so a single broken URL does not fail the whole batch.
            try_catch {
              try {
                // Import the image into Xano storage under the slugified filename
                storage.create_image {
                  value = $normalized_url
                  access = "public"
                  filename = $new_filename
                } as $image_meta
              
                // Build the absolute Xano URL for the stored image
                var $xano_url {
                  value = "https://" ~ ($env.instance_url ?? "") ~ $image_meta.path
                }
              
                // enforce_hidden_fields required (Xano v2.3 bug) - ignore VSCode linter error
                db.add product_image {
                  enforce_hidden_fields = true
                  data = {
                    product_id: $input.product_id
                    src       : $xano_url
                    position  : $next_position
                    active    : true
                  }

                  output = [
                    "id"
                    "created_at"
                    "active"
                    "height"
                    "width"
                    "position"
                    "src"
                    "updated_at"
                    "product_id"
                  ]
                } as $new_image
              
                var.update $created_images {
                  value = $created_images|push:$new_image
                }
              
                // Only advance the position when the image was successfully imported
                var.update $next_position {
                  value = $next_position + 1
                }
              }
            
              catch {
                // Skip this URL on import failure; continue with the rest of the batch
                debug.log {
                  value = "Failed to import image URL: " ~ ($normalized_url|to_text)
                }
              }
            }
          }
        }
      }
    }

    // 5. Import each directly-uploaded file into Xano storage, then create the record.
    // These are already bytes (pattern from 584): no URL normalization or download.
    // $next_position and $created_images are shared with the URL loop above, so uploaded
    // files continue the numbering after the URLs.
    foreach ($input.files ?? []) {
      each as $file_item {
        conditional {
          if ($file_item != null) {
            // Wrapped in try_catch so a single corrupted file does not fail the whole batch.
            try_catch {
              try {
                // Import the uploaded file directly into Xano storage
                storage.create_image {
                  value = $file_item
                  access = "public"
                  filename = ""
                } as $image_meta

                // Build the absolute Xano URL for the stored image
                var $xano_url {
                  value = "https://" ~ ($env.instance_url ?? "") ~ $image_meta.path
                }

                // enforce_hidden_fields required (Xano v2.3 bug) - ignore VSCode linter error
                db.add product_image {
                  enforce_hidden_fields = true
                  data = {
                    product_id: $input.product_id
                    src       : $xano_url
                    position  : $next_position
                    active    : true
                  }

                  output = [
                    "id"
                    "created_at"
                    "active"
                    "height"
                    "width"
                    "position"
                    "src"
                    "updated_at"
                    "product_id"
                  ]
                } as $new_image

                var.update $created_images {
                  value = $created_images|push:$new_image
                }

                // Only advance the position when the image was successfully imported
                var.update $next_position {
                  value = $next_position + 1
                }
              }

              catch {
                // Skip this file on import failure; continue with the rest of the batch
                debug.log {
                  value = "Failed to import uploaded file"
                }
              }
            }
          }
        }
      }
    }
  }

  response = {images: $created_images}
}