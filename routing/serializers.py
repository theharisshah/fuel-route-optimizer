"""Request validation for the route API."""
from rest_framework import serializers


class RouteRequestSerializer(serializers.Serializer):
    start = serializers.CharField(max_length=200, help_text='US place, e.g. "Chicago, IL", or "lat,lng".')
    finish = serializers.CharField(max_length=200, help_text='US place, e.g. "Dallas, TX", or "lat,lng".')
