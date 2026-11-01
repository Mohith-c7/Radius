def calculate_total(price: float, tax: float) -> float:
    return price + tax

class OrderProcessor:
    def __init__(self):
        self.orders = []
    def add_order(self, order):
        self.orders.append(order)
