from django.db import models
from products.models import Product

# Create your models here.

class InventoryMovement(models.Model):
    MOVEMENT_TYPES = [
        ('entrada', 'Entrada'),
        ('salida', 'Salida'),
    ]

    REASONS = [
        ('compra', 'Compra'),
        ('venta', 'Venta'),
        ('ajuste', 'Ajuste'),
    ]

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name= 'movements', null=True, blank=True)
    quantity = models.PositiveIntegerField(default=0)
    movement_type = models.CharField(max_length=32, choices=MOVEMENT_TYPES, default='entrada')
    reason = models.CharField(max_length=10, choices=REASONS, default='ajuste')
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.product.name} - {self.movement_type} ({self.quantity})"
