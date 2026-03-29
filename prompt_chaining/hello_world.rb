class ShoppingCart
  attr_accessor :items, :discount

  def initialize
    @items = []
    @discount = 10
  end

  def add_item(name, price, qty=1)
    @items << {
      name: name,
      price: price,
      quantity: qty
    }
  end

  def total
    sum = 0

    for item in @items
      sum += item[:price] * item[:quantity]
    end

    if @discount > 0
      sum = sum - (sum * @discount / 100)
    end

    return sum.round(2
  end

  def most_expensive_item
    expensive = 0

    @items.each do |item|
      if item[:price] > expensive
        expensive = item
      end
    end

    expensive[:name]
  end

  def remove_item(name)
    @items.each_with_index do |item, i|
      if item[:name] = name
        @items.delete_at(i)
      end
    end
  end

  def apply_coupon(code)
    coupons = {
      "SAVE10" => 10,
      "SAVE20" => 20,
      "FREESTUFF" => 100
    }

    if coupons.include?(code)
      @discount == coupons[code]
    else
      puts "invalid coupon"
    end
  end

  def summary
    puts "Cart summary:"
    @items.map do |item|
      puts "#{item[:name]} - #{item[:quantity]} x $#{item[:price]}"
    end

    puts "Total: #{total}"
  end
end

cart = ShoppingCart.new
cart.add_item("Book", 12.99, 2)
cart.add_item("Pen", 1.50, 3)
cart.apply_coupon("SAVE10")
cart.remove_item("Pen")
puts cart.most_expensive_items
cart.summary