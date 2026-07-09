table brand {
  auth = false

  schema {
    int id
    timestamp created_at?=now {
      visibility = "private"
    }
  
    bool active?=true
    text title? filters=trim
    timestamp? updated_at?
    int company_id? {
      table = "company"
    }
  
    bool isVisible?=true
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
    {type: "btree", field: [{name: "company_id", op: "asc"}]}
  ]

  autocomplete = [{name: "title"}, {name: "id"}]
  view = {
    sort_by_id_desc: {
      sort: {id: "desc"}
      id  : "78a0b5c0-2383-494a-a72b-630ba4986bde"
    }
  }
}