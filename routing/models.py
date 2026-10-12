from django.db import models

# Create your models here.

class FuelStation(models.Model):
    opis_id = models.IntegerField(unique=True)
    name = models.CharField(max_length=255)
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=2)
    price = models.FloatField()
    lat = models.FloatField()
    lng = models.FloatField()

    def __str__(self):
        return f"{self.name} #{self.opis_id} ({self.city}, {self.state}) ${self.price:.3f}"