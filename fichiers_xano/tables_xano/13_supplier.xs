table supplier {
  auth = false

  schema {
    int id
    timestamp created_at?=now {
      visibility = "private"
    }
  
    bool active?=true
    int address_id? {
      table = "address"
    }
  
    int? company_id? {
      table = "company"
    }
  
    text name? filters=trim
    timestamp? updated_at?
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
    {
      name : "supplier_search"
      lang : "french"
      type : "search"
      field: [{name: "name", op: "A"}]
    }
    {type: "btree", field: [{name: "company_id", op: "asc"}]}
  ]

  view = {
    sort_by_desc: {
      sort: {id: "desc"}
      id  : "b3d36878-94fb-4d5d-bf8a-fb522089f30b"
    }
  }
}