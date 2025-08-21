from decimal import Decimal
from django.db import transaction
from django.db.models import Prefetch, QuerySet
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import viewsets, permissions, status
from django.utils.dateparse import parse_date
from inventory.models import InventoryMovement
from products.models import Product
from .models import Order, OrderItem
from .serializers import OrderSerializer, OrderItemWriteSerializer, OrderItemDecreaseSerializer, OrderItemDeleteSerializer
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.decorators import action
from django.db.models import F
from django.utils import timezone

# Create your views here.

class OrderViewSet(viewsets.ModelViewSet):
    queryset = Order.objects.all()
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = OrderSerializer

    def get_queryset(self) -> QuerySet[Order]:
        request: Request = self.request
        qs = (
            Order.objects.all()
            .select_related()
            .prefetch_related(Prefetch("items", queryset=OrderItem.objects.select_related("product")))
            .order_by("-created_at")
        )
        
        status_val = request.query_params.get("status")
        if status_val:
            qs = qs.filter(status=status_val)

        date_from_raw = request.query_params.get('date_from')
        if date_from_raw:
            df = parse_date(date_from_raw)
            if df:
                qs = qs.filter(created_at__date__gte=df)

        date_to_raw = request.query_params.get('date_to')
        if date_to_raw:
            dt = parse_date(date_to_raw)
            if dt:
                qs = qs.filter(created_at__date__lte=dt)

        change_type = request.query_params.get("last_change_type")
        if change_type:
            qs = qs.filter(last_change_type=change_type)

        last_change_from = request.query_params.get("last_change_from")
        if last_change_from:
            lcf = parse_date(last_change_from)
            if lcf:
                qs = qs.filter(last_change_at__date__gte=lcf)

        last_change_to = request.query_params.get("last_change_to")
        if last_change_to:
            lct = parse_date(last_change_to)
            if lct:
                qs = qs.filter(last_change_at__date__lte=lct)

        return qs

    def perform_update(self, serializer):
        instance = serializer.save()
        instance.last_change_at = timezone.now()
        instance.last_change_type = Order.CHANGE_UPDATE
        instance.save(update_fields=["last_change_at", "last_change_type"])

    @action(detail=True, methods=["patch"], url_path="complete")
    def complete(self, request, pk=None):
        order = self.get_object()

        if order.status == Order.COMPLETED:
            return Response({"detail": "Order is already completed."}, status=status.HTTP_400_BAD_REQUEST)
        if order.status == Order.CANCELED:
            return Response({"detail": "Canceled orders cannot be completed."}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():

            already_applied = True
            for item in order.items.select_related("product").all():
                exists_mv = InventoryMovement.objects.filter(
                    product=item.product,
                    movement_type="salida",
                    reason="venta",
                    timestamp__gte=order.created_at
                ).exists()
                if not exists_mv:
                    already_applied = False
                    break

            if not already_applied:

                insufficient = []
                for item in order.items.select_related("product").all():
                    if item.product.stock < item.quantity:
                        insufficient.append({
                            "product_id": item.product_id,
                            "name": item.product.name,
                            "requested": item.quantity,
                            "available": item.product.stock,
                        })
                if insufficient:
                    return Response(
                        {"detail": "Insufficient stock for some products.", "items": insufficient},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                for item in order.items.select_related("product").all():
                    Product.objects.filter(pk=item.product_id).update(stock=F("stock") - item.quantity)
                    InventoryMovement.objects.create(
                        product=item.product,
                        quantity=item.quantity,
                        movement_type="salida",
                        reason="venta",
                    )

            order.status = Order.COMPLETED
            order.last_change_at = timezone.now()
            order.last_change_type = Order.CHANGE_COMPLETED
            order.save(update_fields=["status", "last_change_at", "last_change_type"])

        return Response(self.get_serializer(order).data, status=status.HTTP_200_OK)

    @extend_schema(
        description="Add one product to a pending order. Validates stock, decreases it, records an InventoryMovement, updates order total and last-change fields.",
        request=OrderItemWriteSerializer,
        responses={200: OrderSerializer, 400: OpenApiTypes.OBJECT},
        tags=["orders"],
        operation_id="order_add_item",
    )
    @action(detail=True, methods=["post"], url_path="add-item", permission_classes=[permissions.IsAuthenticated])
    def add_item(self, request, pk=None):
        order = self.get_object()

        if order.status in [Order.COMPLETED, Order.CANCELED]:
            return Response(
                {"detail": "You can't modify a completed/canceled order."},
                status=status.HTTP_400_BAD_REQUEST
            )

        payload = OrderItemWriteSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        product = payload.validated_data["product"]
        qty = payload.validated_data["quantity"]

        with transaction.atomic():
            product = Product.objects.select_for_update().get(pk=product.pk)

            if product.stock < qty:
                return Response(
                    {"detail": f"Insufficient stock for '{product.name}'.", "available": product.stock},
                    status=status.HTTP_400_BAD_REQUEST
                )

            item = (
                OrderItem.objects
                .select_for_update()
                .filter(order=order, product=product)
                .first()
            )

            if item:
                unit_price = item.price
                OrderItem.objects.filter(pk=item.pk).update(quantity=F("quantity") + qty)
            else:
                unit_price = product.price
                item = OrderItem.objects.create(
                    order=order,
                    product=product,
                    quantity=qty,
                    price=unit_price
                )

            Product.objects.filter(pk=product.pk).update(stock=F("stock") - qty)
            InventoryMovement.objects.create(
                product=product,
                quantity=qty,
                movement_type="salida",
                reason="venta",
            )

            addition = Decimal(qty) * unit_price
            Order.objects.filter(pk=order.pk).update(total=F("total") + addition)

            order.last_change_at = timezone.now()
            order.last_change_type = Order.CHANGE_UPDATE
            order.save(update_fields=["last_change_at", "last_change_type"])

        order.refresh_from_db()
        return Response(self.get_serializer(order).data, status=status.HTTP_200_OK)

    @extend_schema(
        description=(
                "Decrease quantity of a product in a pending order. "
                "If resulting quantity is 0, the item line is removed. "
                "Returns stock to inventory and records an 'entrada' movement (reason: 'ajuste_orden')."
        ),
        request=OrderItemDecreaseSerializer,
        responses={200: OrderSerializer, 400: OpenApiTypes.OBJECT},
        tags=["orders"],
        operation_id="order_remove_item",
    )
    @action(detail=True, methods=["post"], url_path="remove-item", permission_classes=[permissions.IsAuthenticated])
    def remove_item(self, request, pk=None):
        order = self.get_object()

        if order.status in [Order.COMPLETED, Order.CANCELED]:
            return Response(
                {"detail": "You can't modify a completed/canceled order."},
                status=status.HTTP_400_BAD_REQUEST
            )

        payload = OrderItemDecreaseSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        product = payload.validated_data["product"]
        dec_qty = payload.validated_data["quantity"]

        with transaction.atomic():
            product = Product.objects.select_for_update().get(pk=product.pk)
            item = (
                OrderItem.objects
                .select_for_update()
                .filter(order=order, product=product)
                .first()
            )
            if not item:
                return Response(
                    {"detail": f"Product '{product.name}' is not in this order."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            remove_units = min(dec_qty, item.quantity)
            unit_price = item.price

            Product.objects.filter(pk=product.pk).update(stock=F("stock") + remove_units)
            InventoryMovement.objects.create(
                product=product,
                quantity=remove_units,
                movement_type="entrada",
                reason="ajuste",
            )

            if remove_units == item.quantity:
                line_total = Decimal(item.quantity) * unit_price
                item.delete()
            else:
                OrderItem.objects.filter(pk=item.pk).update(quantity=F("quantity") - remove_units)
                line_total = Decimal(remove_units) * unit_price

            Order.objects.filter(pk=order.pk).update(total=F("total") - line_total)

            order.last_change_at = timezone.now()
            order.last_change_type = Order.CHANGE_UPDATE
            order.save(update_fields=["last_change_at", "last_change_type"])

        order.refresh_from_db()
        return Response(self.get_serializer(order).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["patch"], url_path="cancel")
    def cancel(self, request, pk=None):
        order = self.get_object()
        if order.status == Order.COMPLETED:
            return Response({"detail": "Completed orders cannot be canceled."}, status=400)
        if order.status == Order.CANCELED:
            return Response({"detail": "Order is already canceled."}, status=400)
        order.status = Order.CANCELED
        order.last_change_at = timezone.now()
        order.last_change_type = Order.CHANGE_CANCELED
        order.save(update_fields=["status", "last_change_at", "last_change_type"])

        return Response(self.get_serializer(order).data)

    def destroy(self, request, *args, **kwargs):
        order = self.get_object()

        order.deleted_at = timezone.now()
        if order.status not in [Order.CANCELED, Order.COMPLETED]:
            order.status = Order.CANCELED

        order.last_change_at = timezone.now()
        order.last_change_type = Order.CHANGE_DELETE
        order.save(update_fields=["deleted_at", "status", "last_change_at", "last_change_type"])

        return Response(status=status.HTTP_204_NO_CONTENT)