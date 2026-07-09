table product_option {
  auth = false

  schema {
    int id
    timestamp created_at?=now {
      visibility = "private"
    }
  
    bool active?=true
    text name? filters=trim
    int position?
    timestamp? updated_at?
    text[] values? filters=trim
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
  
    // 1 : PRODUCT, 2 : PREDEFINED (reusable)
    enum scope?=1 {
      values = ["1", "2"]
      visibility = "private"
    }
  
    int? company_id? {
      table = "company"
      visibility = "private"
    }
  }

  index = [
    {type: "primary", field: [{name: "id"}]}
    {type: "btree", field: [{name: "created_at", op: "desc"}]}
    {type: "btree", field: [{name: "product_id", op: "asc"}]}
  ]

  view = {
    sort_by_id_desc: {
      sort: {id: "desc"}
      id  : "18e0a14c-9069-4383-a775-35a88dd4f3b1"
    }
  }
}