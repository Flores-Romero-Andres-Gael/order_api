from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema, extend_schema_field
from rest_framework import serializers
from django.db import transaction
from inventory.models import InventoryMovement
from products.models import Product
from .models import Order, OrderItem
from django.db.models import F

class OrderItemReadSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    total_price = serializers.SerializerMethodField()

    class Meta:
        model = OrderItem
        fields = ["id", "product", "product_name", "quantity", "price", "total_price"]

    @extend_schema_field(OpenApiTypes.NUMBER)
    def get_total_price(self, obj):
        return obj.quantity * obj.price

class OrderItemWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderItem
        fields = ["product", "quantity"]

    def validate(self, attrs):
        if attrs["quantity"] <= 0:
            raise serializers.ValidationError("Quantity must be greater than 0.")
        return attrs

class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemReadSerializer(many=True, read_only=True)
    items_data = OrderItemWriteSerializer(many=True, write_only=True, required=True)

    class Meta:
        model = Order
        fields = ["id", "customer_name", "total", "status", "created_at", "last_change_at", "last_change_type", "items", "items_data"]
        read_only_fields = ["id, created_at", "last_change_at", "last_change_type", "items", "total"]

    def validate_items_data(self, value):
        if not value:
            raise serializers.ValidationError("Order must contain at least one item.")
        return value

    @transaction.atomic
    def create(self, validated_data):
        items_data = validated_data.pop("items_data")
        order = Order.objects.create(**validated_data)

        total = 0
        product_ids = [it["product"].id for it in items_data]
        products = {p.id: p for p in Product.objects.select_related().filter(id__in=product_ids)}

        count_stock = []
        for item in items_data:
            product = products[item["product"].id]
            qty = item["quantity"]
            if product.stock < qty:
                raise serializers.ValidationError(
                    {"items_data": [f"Insufficient stock for product '{product.name}' (available {product.stock})."]}
                )
        for item in items_data:
            product = products[item["product"].id]
            qty = item["quantity"]
            price_now = product.price
            OrderItem.objects.create(order=order, product=product, quantity=qty, price=price_now)
            Product.objects.filter(pk=product.id).update(stock=F("stock") - qty)

            InventoryMovement.objects.create(
                product=product,
                quantity=qty,
                movement_type = "salida",
                reason = "venta"
            )

            total += qty * price_now

        order.total = total
        order.save(update_fields=["total"])
        return order

class OrderItemDecreaseSerializer(serializers.Serializer):
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all())
    quantity = serializers.IntegerField(min_value=1)

class OrderItemDeleteSerializer(serializers.Serializer):
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all())