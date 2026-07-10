table tags {
  auth = false

  schema {
    int id
    timestamp created_at?=now {
      visibility = "private"
    }
  
    bool active?=true
    text title? filters=trim
    int company_id? {
      table = "company"
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
    {type: "btree", field: [{name: "company_id", op: "asc"}]}
  ]

  view = {
    sort_by_id_desc: {
      sort: {id: "desc"}
      id  : "9b0091f6-2199-4fa2-87c3-b0220c73f73e"
    }
  }
}