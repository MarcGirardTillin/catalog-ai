table category {
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
  
    int parent_id? {
      table = "category"
    }
  }

  index = [
    {type: "primary", field: [{name: "id"}]}
    {type: "btree", field: [{name: "created_at", op: "desc"}]}
    {
      name : "category_search_title"
      lang : "french"
      type : "search"
      field: [{name: "title", op: "A"}]
    }
    {type: "btree", field: [{name: "company_id", op: "asc"}]}
  ]

  view = {
    sort_by_id_desc: {
      sort: {id: "desc"}
      id  : "d9fe2dce-783e-490c-bf6e-2395578e8ac2"
    }
  }
}