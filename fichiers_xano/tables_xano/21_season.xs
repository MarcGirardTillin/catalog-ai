table season {
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
      
        int id_group?
      }
    }
  }

  index = [
    {type: "primary", field: [{name: "id"}]}
    {type: "btree", field: [{name: "created_at", op: "desc"}]}
    {
      name : "season_search_title"
      lang : "french"
      type : "search"
      field: [{name: "title", op: "A"}]
    }
    {type: "btree", field: [{name: "company_id", op: "asc"}]}
  ]

  view = {
    sort_by_id_desc: {
      sort: {id: "desc"}
      id  : "071c7970-fb3f-4793-90b4-e0dbe404768a"
    }
  }
}