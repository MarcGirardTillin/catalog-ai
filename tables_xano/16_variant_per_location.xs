table variant_per_location {
  auth = false

  schema {
    int id
    timestamp created_at?=now {
      visibility = "private"
    }
  
    bool active?=true
    int location_id? {
      table = "location"
    }
  
    int quantity?
    int out_of_stock_threshold?
    int product_variant_id? {
      table = "product_variant"
    }
  }

  index = [
    {type: "primary", field: [{name: "id"}]}
    {type: "btree", field: [{name: "created_at", op: "desc"}]}
    {
      type : "btree"
      field: [{name: "product_variant_id", op: "asc"}]
    }
    {type: "btree", field: [{name: "location_id", op: "asc"}]}
  ]

  view = {
    sort_by_id_desc: {
      sort: {id: "desc"}
      id  : "9cb8e380-6413-42b2-b4a0-82101a5c1427"
    }
  }
}