table composition {
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
}