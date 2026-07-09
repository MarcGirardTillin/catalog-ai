table price {
  auth = false

  schema {
    int id
    timestamp created_at?=now {
      visibility = "private"
    }
  
    bool active?=true
    decimal amount?
    int currency_code_id?=1 {
      table = "currency_code"
    }
  }

  index = [
    {type: "primary", field: [{name: "id"}]}
    {type: "btree", field: [{name: "created_at", op: "desc"}]}
  ]

  view = {
    sort_by_id_desc: {
      sort: {id: "desc"}
      id  : "fbb16fb7-bf5a-4a02-8b1c-f3fa45d66af8"
    }
  }
}