table product {
  auth = false

  schema {
    int id
    timestamp created_at?=now {
      visibility = "private"
    }
  
    bool active?=true
    int company_id? {
      table = "company"
    }
  
    int brand_id? {
      table = "brand"
    }
  
    int category_id? {
      table = "category"
    }
  
    text description? filters=trim
    text description_html? filters=trim
    text short_description? filters=trim
    text short_description_html? filters=trim {
      visibility = "private"
    }
  
    int discount_id? {
      table = "discount"
    }
  
    text harmonized_system_code? filters=trim
    text? manufacturing_country?
    text product_reference_code? filters=trim
    timestamp? published_at?
    int season_id? {
      table = "season"
    }
  
    // 1: Inactif, 2: Actif, 3: Archivé
    enum status?=1 {
      values = ["1", "2", "3"]
    }
  
    int supplier_id? {
      table = "supplier"
    }
  
    text title? filters=trim
    timestamp? updated_at?
    int tax_id? {
      table = "tax"
    }
  
    int department_id? {
      table = "department"
    }
  
    int[] tags_id? {
      table = "tags"
    }
  
    int composition_id? {
      table = "composition"
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
  
    text title_label? filters=trim
    text supplier_product_reference_code? filters=trim
    int[] category_ids? {
      table = "category"
    }
  
    enum product_type?=PHYSICAL {
      values = ["PHYSICAL", "SERVICE", "DIGITAL"]
      visibility = "private"
    }
  
    text meta_title? filters=trim {
      visibility = "private"
    }
  
    text meta_description? filters=trim {
      visibility = "private"
    }
  }

  index = [
    {type: "primary", field: [{name: "id"}]}
    {type: "btree", field: [{name: "created_at", op: "desc"}]}
    {
      name : "search_product"
      lang : "french"
      type : "search"
      field: [
        {name: "title", op: "A"}
        {name: "product_reference_code", op: "A"}
        {name: "title_label", op: "B"}
        {name: "supplier_product_reference_code", op: "C"}
      ]
    }
    {type: "btree", field: [{name: "company_id", op: "asc"}]}
    {type: "btree", field: [{name: "active", op: "asc"}]}
    {type: "btree", field: [{name: "status", op: "asc"}]}
    {type: "btree", field: [{name: "supplier_id", op: "asc"}]}
    {type: "btree", field: [{name: "category_id", op: "asc"}]}
    {type: "btree", field: [{name: "season_id", op: "asc"}]}
    {type: "btree", field: [{name: "brand_id", op: "asc"}]}
  ]

  autocomplete = [{name: "title"}, {name: "product_reference_code"}]
  view = {
    sort_by_id_desc: {
      sort: {id: "desc"}
      id  : "58461cfe-bfc3-4a04-a4ec-705865c17627"
    }
  }
}