// deactivate product_image records
query "product_image/deactivate" verb=PUT {
  api_group = "Tillin API endpoints"
  auth = "user"

  input {
    int[] product_image_ids? filters=min:1
  }

  stack {
    db.get user {
      field_name = "id"
      field_value = $auth.id
      output = ["id", "company"]
    } as $user
  
    db.query product_image {
      join = {
        product: {
          table: "product"
          where: $db.product.id == $db.product_image.product_id && $db.product.company_id == $user.company
        }
      }
    
      where = $db.product_image.id in $input.product_image_ids && $db.product_image.active == true
      return = {type: "list"}
    } as $product_images
  
    array.map ($product_images) {
      by = {id: $this.id, active: false}
    } as $product_images_to_update
  
    db.bulk.patch product_image {
      items = $product_images_to_update
    } as $product_images
  }

  response = $product_images
}