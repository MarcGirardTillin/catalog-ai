// deactivate product_image records
query "product_image/deactivate" verb=PUT {
  api_group = "Tillin API endpoints"
  auth = "user"

  input {
    int[] product_image_ids? filters=min:1
  }

  stack {
    array.map ($input.product_image_ids) {
      by = {id: $this, active: false}
    } as $product_images_to_update
  
    db.bulk.patch product_image {
      items = $product_images_to_update
    } as $product_images
  }

  response = $product_images
}