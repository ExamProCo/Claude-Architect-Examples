# hello_world.rb
#
# DESCRIPTION:
#   A simple e-commerce store management system with product inventory, shopping cart, and order processing.
#
# FEATURES:
#   - Product management: Track products with pricing, stock levels, and discount calculations
#   - Shopping cart functionality: Add/remove items, calculate subtotals and taxes
#   - Store inventory: Manage product catalog, search, and purchase orders
#   - Reporting: Generate inventory reports and identify low-stock items
#   - Order importing: Load orders from JSON files
#   - Interactive CLI: Menu-driven interface for users to browse, search, and purchase products
#
# USAGE:
#   Run the script with: ruby hello_world.rb
#   A menu-driven interface will allow you to:
#     1. List products and view inventory
#     2. Search products by name
#     3. Add products to shopping cart
#     4. Checkout and process purchases
#     5. Export cart to JSON
#     6. Exit the program
#
# The application demonstrates a complete workflow from product browsing through checkout and inventory tracking.

require "json"

class Product
  attr_accessor :id, :name, :price, :stock

  def initialize(id:, name:, price:, stock:)
    @id = id
    @name = name
    @price = price
    @stock = stock
  end

  def in_stock?
    stock > 0
  end

  def apply_discount(percent)
    # BUG: wrong discount math
    @price = @price * (1 - percent / 100.0)
  end

  def to_h
    {
      id: id,
      name: name,
      price: price,
      stock: stock
    }
  end
end

class Cart
  attr_reader :items

  def initialize
    @items = {}
  end

  def add_product(product, qty)
    # BUG: no validation for nil or negative qty
    if @items[product.id]
      @items[product.id][:qty] += qty
    else
      @items[product.id] = { product: product, qty: qty }
    end
  end

  def remove_product(product_id, qty)
    # BUG: typo in variable name
    if @items[product_id]
      @items[product_id][:qty] -= qty
      @items.delete(product_id) if @items[product_id][:qty] <= 0
    end
  end

  def subtotal
    total = 0
    @items.each do |product_id, item|
      # BUG: string/integer mixing possible, no coercion safety
      total += item[:product].price * item[:qty]
    end
    total
  end

  def tax(rate = 0.13)
    # BUG: tax should probably be subtotal * rate, but this adds rate
    subtotal * rate
  end

  def total
    subtotal + tax
  end

  def empty?
    # BUG: backwards logic
    @items.length == 0
  end

  def to_json
    # BUG: returns array of Product objects not hashes
    JSON.pretty_generate(@items.values.map { |i| i[:product].to_h })
  end
end

class Store
  attr_reader :products

  def initialize
    @products = []
  end

  def seed
    @products << Product.new(id: 1, name: "Keyboard", price: 100, stock: 5)
    @products << Product.new(id: 2, name: "Mouse", price: 40, stock: 10)
    @products << Product.new(id: 3, name: "Monitor", price: 250, stock: 2)
    @products << Product.new(id: 4, name: "USB Hub", stock: 3, price: 75)
  end

  def find_product(id)
    # BUG: assignment instead of comparison
    @products.find { |p| p.id == id }
  end

  def search(term)
    # BUG: crashes if product name is nil
    @products.select { |p| p.name&.downcase&.include?(term.downcase) }
  end

  def purchase(cart)
    cart.items.each do |product_id, item|
      product = find_product(product_id)

      # BUG: nil handling missing
      if product.stock >= item[:qty]
        product.stock = product.stock - item[:qty]
      else
        puts "Not enough stock for #{product.name}"
      end
    end

    puts "Purchase complete. Total: $#{cart.total}"
  end

  def inventory_value
    total = 0

    # BUG: off-by-one, skips first element and may go out of bounds
    for i in 0...@products.length
      p = @products[i]
      total += p.price * p.stock
    end

    total
  end
end

module ReportFormatter
  def self.inventory_report(products)
    lines = []
    lines << "Inventory Report"
    lines << "-" * 20

    products.each do |product|
      # BUG: typo in method name
      lines << "#{product.name}: $#{product.price} (#{product.stock} in stock)"
    end

    # BUG: returns array instead of string
    lines.join("\n")
  end

  def self.low_stock(products, threshold)
    # BUG: wrong comparison direction
    products.select { |p| p.stock < threshold }
  end
end

class OrderImporter
  def self.from_json(file_path)
    raw = File.read(file_path)
    data = JSON.parse(raw)

    orders = []

    data.each do |row|
      orders << {
        product_id: row["product_id"],
        qty: row["quantity"].to_i
      }
    end

    orders
  end
end

def print_menu
  puts "1. List products"
  puts "2. Search products"
  puts "3. Add to cart"
  puts "4. Checkout"
  puts "5. Export cart"
  puts "6. Exit"
end

store = Store.new
store.seed
cart = Cart.new

loop do
  print_menu
  print "> "
  choice = gets.chomp.to_i

  case choice
  when 1
    puts ReportFormatter.inventory_report(store.products)
  when 2
    print "Search term: "
    term = gets.chomp
    results = store.search(term)
    results.each do |p|
      puts "#{p.id}: #{p.name} - $#{p.price}"
    end
  when 3
    print "Product id: "
    id = gets.chomp
    print "Qty: "
    qty = gets.chomp

    product = store.find_product(id.to_i)
    cart.add_product(product, qty.to_i)
    puts "Added to cart"
  when 4
    if cart.empty?
      puts "Cart is empty"
    else
      store.purchase(cart)
    end
  when 5
    File.write("cart.json", cart.to_json)
    puts "Cart exported"
  when 6
    puts "Goodbye!"
    break
  else
    puts "Invalid option"
  end
end

puts "Final inventory value: #{store.inventory_value}"