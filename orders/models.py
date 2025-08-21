from django.utils import timezone
from django.db import models
from products.models import Product

# Create your models here.

class Order(models.Model):
    PENDING = "pendiente"
    COMPLETED = "completada"
    CANCELED = "cancelada"
    STATUS_CHOICES = (
        (PENDING, "Pendiente"),
        (COMPLETED, "Completada"),
        (CANCELED, "Cancelada"),
    )

    CHANGE_UPDATE = "update"
    CHANGE_COMPLETED = "completed"
    CHANGE_CANCELED = "canceled"
    CHANGE_DELETE = "delete"
    CHANGE_CREATED = "created"
    CHANGE_STATUS = (
        (CHANGE_UPDATE, "Update"),
        (CHANGE_COMPLETED, "Completed"),
        (CHANGE_CANCELED, "Canceled"),
        (CHANGE_DELETE, "Delete"),
        (CHANGE_CREATED, "Created"),
    )

    id = models.AutoField(primary_key=True)
    customer_name = models.CharField(max_length=100)
    total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    last_change_at = models.DateTimeField(default=timezone.now)
    last_change_type = models.CharField(max_length=10, choices=CHANGE_STATUS, default=CHANGE_CREATED)

    def __str__(self):
        return f"Order # {self.id} - {self.customer_name}"

    class Meta:
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["last_change_type"]),
            models.Index(fields=["last_change_at"]),
        ]

class OrderItem(models.Model):

    id = models.AutoField(primary_key=True)
    order = models.ForeignKey(Order, related_name="items", on_delete=models.CASCADE)
    product = models.ForeignKey(Product, related_name="items", on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField()
    price = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return f"{self.product.name} x {self.quantity}"

    @property
    def total(self):
        return self.quantity * self.price