"""API endpoint and map page for planning a trip."""
from urllib.parse import urlencode

from django.shortcuts import render
from django.urls import reverse
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .fuel import FuelPlanError
from .ors import LocationNotFound, RoutingError
from .serializers import RouteRequestSerializer
from .services import plan_trip


class RoutePlanView(APIView):
    """GET or POST {"start": ..., "finish": ...} -> route, fuel stops and total fuel cost."""

    def get(self, request):
        return self._plan(request, request.query_params)

    def post(self, request):
        return self._plan(request, request.data)

    def _plan(self, request, data):
        serializer = RouteRequestSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        start = serializer.validated_data["start"]
        finish = serializer.validated_data["finish"]

        try:
            result = plan_trip(start, finish)
        except LocationNotFound as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except FuelPlanError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        except RoutingError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        map_path = reverse("route-map") + "?" + urlencode({"start": start, "finish": finish})
        result["map_url"] = request.build_absolute_uri(map_path)
        return Response(result)


def route_map(request):
    """HTML page that draws the planned route and fuel stops on a map."""
    start = request.GET.get("start", "").strip()
    finish = request.GET.get("finish", "").strip()
    context = {"start": start, "finish": finish, "trip": None, "error": None}

    if start and finish:
        try:
            context["trip"] = plan_trip(start, finish)
        except (RoutingError, FuelPlanError) as exc:
            context["error"] = str(exc)

    return render(request, "routing/map.html", context)
