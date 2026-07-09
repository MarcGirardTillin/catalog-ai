table product_variant {
  auth = false

  schema {
    int id
    timestamp created_at?=now {
      visibility = "private"
    }
  
    bool active?=true
    text? barcode? filters=trim
    int[] discount_id? {
      table = "discount"
    }
  
    int global_out_of_stock_threshold?
    int? product_image_id? {
      table = "product_image"
    }
  
    text[:3] options? filters=trim
    int position?
    int? price_with_discount? {
      table = "price"
    }
  
    text sku? filters=trim
    int price_id? {
      table = "price"
    }
  
    text title? filters=trim
    timestamp? updated_at?
    decimal weight?
    enum? weight_unit?=1 {
      values = ["1", "2", "3", "4"]
    }
  
    int wholesale_price? {
      table = "price"
    }
  
    int product_id? {
      table = "product"
    }
  
    int tax_id? {
      table = "tax"
    }
  
    int wholesale_discount_id? {
      table = "discount_amount_rule"
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
  
    decimal wholesale_list_price? {
      visibility = "private"
    }
  
    decimal weighted_average_price?
    decimal wholesale_price_tax_excl?
    decimal price_tax_incl?
    int[] season_id? {
      table = "season"
    }
  
    decimal wholesale_discount_amount?
    enum wholesale_discount_type?=1 {
      values = ["1", "2"]
    }
  
    int wholesale_tax_id? {
      table = "tax"
    }
  }

  index = [
    {type: "primary", field: [{name: "id"}]}
    {type: "btree", field: [{name: "created_at", op: "desc"}]}
    {
      name : "search_variant"
      lang : "french"
      type : "search"
      field: [{name: "barcode", op: "A"}, {name: "sku", op: "B"}]
    }
    {type: "btree", field: [{name: "barcode", op: "asc"}]}
    {type: "btree", field: [{name: "sku", op: "asc"}]}
    {type: "btree", field: [{name: "product_id", op: "asc"}]}
    {type: "btree", field: [{name: "active", op: "asc"}]}
  ]

  view = {
    Sorted_by_id_desc: {
      sort: {id: "desc"}
      id  : "759f6605-c699-4dcb-a944-2f9060140d11"
    }
  }
}