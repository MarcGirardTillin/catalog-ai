table tax {
  auth = false

  schema {
    int id
    timestamp created_at?=now {
      visibility = "private"
    }
  
    bool active?=true
    decimal rate?
    text title? filters=trim
    timestamp? updated_at?
    int company_id? {
      table = "company"
    }
  
    object[] origin? {
      schema {
        int id?
        enum third_party? {
          values = ["Shopify", "Pretashop", "Woocommerce"]
        }
      
        int location_id? {
          table = "location"
        }
      }
    }
  
    text country? filters=trim
  
    // // Code lettre NF525 — A (20%), B (10%), C (5.5%), D (2.1%), E (0%) — affiché sur ticket/note
    text code? filters=trim
  }

  index = [
    {type: "primary", field: [{name: "id"}]}
    {type: "btree", field: [{name: "created_at", op: "desc"}]}
    {type: "btree", field: [{name: "company_id", op: "asc"}]}
    {type: "btree", field: [{name: "rate", op: "asc"}]}
  ]

  autocomplete = [{name: "title"}, {name: "rate"}, {name: "company_id"}]
  view = {
    sort_by_id_desc: {
      sort: {id: "desc"}
      id  : "0d9e3610-4e21-45ff-8560-bef9ac37ce07"
    }
  }
}