from django.db import models
import uuid

from users.models import Employee


class SubDealer(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    shop_name = models.CharField(max_length=255)
    phone = models.CharField(max_length=15)
    card_image = models.ImageField(upload_to='visiting_card/', blank=True, null=True)
    owner_name = models.CharField(max_length=255)
    gst_no = models.CharField(max_length=50, blank=True, null=True)
    contact_person = models.CharField(max_length=255, blank=True, null=True)
    contact_person_phone = models.CharField(max_length=15, blank=True, null=True)

    store_picture = models.ImageField(upload_to='dealer_store_pictures/', null=True, blank=True)
    shop_number = models.CharField(max_length=255,verbose_name="House No, House name, Road name")
    street = models.CharField(max_length=255,verbose_name="Village, Post Office, City")
    district = models.CharField(max_length=255, verbose_name="District")
    state = models.CharField(max_length=255,verbose_name="State")
    country = models.CharField(max_length=255,verbose_name="Country")
    pincode = models.CharField(max_length=6,verbose_name="Pin code")
    landmark = models.CharField(max_length=255, blank=True, null=True)

    secondary_address = models.TextField(blank=True, null=True)
    secondary_pincode = models.IntegerField(blank=True, null=True)

    latitude = models.FloatField(blank=True, null=True)
    longitude = models.FloatField(blank=True, null=True)

    email = models.EmailField(blank=True, null=True)
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="dealer")
    temp_handeler = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="temp_handler", null=True, blank=True)
    temp_handeler_expiry = models.DateField(blank=True, null=True)

    rank = models.CharField(
        max_length=5, choices=[("A", "A"), ("B", "B"), ("C", "C")], default="C"
    )

    is_deleted = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


    def __str__(self):
        return self.shop_name
