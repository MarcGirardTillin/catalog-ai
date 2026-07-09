table product_image {
  auth = false

  schema {
    int id
    timestamp created_at?=now {
      visibility = "private"
    }
  
    bool active?=true
    decimal height?
    decimal width?
    int position?
    text src? filters=trim
    timestamp? updated_at?
    int product_id? {
      table = "product"
    }
  
    object[] origin? {
      schema {
        text id?
        enum third_party? {
          values = ["Shopify", "Prestashop", "Woocommerce", "Wix", "Prestashop16"]
        }
      
        int location_id? {
          table = "location"
        }
      }
    }
  }

  index = [
    {type: "primary", field: [{name: "id"}]}
    {type: "btree", field: [{name: "created_at", op: "desc"}]}
    {type: "btree", field: [{name: "product_id", op: "asc"}]}
  ]

  view = {
    product_image_sort_date_desc: {
      sort: {id: "desc"}
      id  : "89000e5d-fcb4-4d14-a014-3e491254cd71"
    }
    sort_by_id_desc             : {
      sort: {id: "desc"}
      id  : "150f2b77-f5c9-4363-96ca-3975e2ea3b25"
    }
  }
}