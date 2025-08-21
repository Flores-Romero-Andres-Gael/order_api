from django.shortcuts import render
from django.contrib.auth import get_user_model
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken
from .serializers import UserSerializer
from drf_spectacular.utils import extend_schema, OpenApiExample

User = get_user_model()

# Create your views here.
@extend_schema(
    description="Register a new user account.",
    request={
        "application/json": {
            "example": {
                "username": "john_doe",
                "email": "john@example.com",
                "password": "secure123",
                "is_admin": False
            }
        }
    },
    responses={
        201: UserSerializer,
        400: OpenApiExample(
            name="Validation Error",
            value={"email": ["Email already exists."],
                   "username": ["Username already exists."]},
            response_only=True,
            status_codes=["400"]
        )
    }
)

@api_view(['POST'])
@permission_classes([AllowAny])
def register(request):
    serializer = UserSerializer(data=request.data, context={'request': request})

    if serializer.is_valid():
        user = serializer.save()
        user.set_password(request.data['password'])
        user.save()

        refresh = RefreshToken.for_user(user)

        return Response({'refresh': str(refresh), "access": str(refresh.access_token), "user": serializer.data},
                        status=status.HTTP_201_CREATED)

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@extend_schema(
    description="Get authenticated user's profile info.",
    responses={200: UserSerializer}
)
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def profile(request):
    serializer = UserSerializer(instance=request.user, context={'request': request})
    return Response(serializer.data, status=status.HTTP_200_OK)
