from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer, TokenRefreshSerializer
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.exceptions import AuthenticationFailed
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.db.models import Q
from users.models import Employee, LoginHistory, EmployeeRole

def validate_employee_id_num(value, instance=None):
    if value < 1:
        raise serializers.ValidationError("Employee ID number must be a positive integer starting from 1.")

    # Get all existing employeeidnum values, excluding the current instance being updated
    queryset = Employee.objects.all()
    if instance and instance.pk:
        queryset = queryset.exclude(pk=instance.pk)
    
    existing_ids = set(queryset.values_list('employeeidnum', flat=True))

    if value in existing_ids:
        raise serializers.ValidationError("This employee ID number is already taken (including by deleted employees).")

    # Find unoccupied numbers strictly less than value
    unoccupied = [y for y in range(1, value) if y not in existing_ids]

    if len(unoccupied) > 1:
        raise serializers.ValidationError(
            f"You cannot skip multiple numbers. Gaps strictly less than {value} are: {unoccupied}. "
            f"At most one number is allowed to be empty."
        )
    return value


def log_error_to_file(exception, username=None):
    import os
    import traceback
    from django.conf import settings
    from django.utils import timezone

    log_path = os.path.join(settings.BASE_DIR, 'error_log.txt')
    timestamp = timezone.now().strftime('%Y-%m-%d %H:%M:%S')
    user_str = username if username else 'AnonymousUser'
    tb_str = traceback.format_exc()
    
    log_entry = (
        f"========================================\n"
        f"Timestamp: {timestamp}\n"
        f"Username: {user_str}\n"
        f"Exception: {str(exception)}\n"
        f"Traceback:\n{tb_str}"
        f"========================================\n\n"
    )
    try:
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(log_entry)
    except Exception as e:
        import sys
        sys.stderr.write(f"Failed to write to error_log.txt: {str(e)}\n")


class FlexibleRoleField(serializers.PrimaryKeyRelatedField):
    """
    Accepts either an EmployeeRole UUID (primary key), a role name string ('OWNER', 'MANAGER'),
    or an EmployeeRole instance.
    'OWNER' resolves to None because OWNER is a special system role handled in code (not in DB table).
    """
    def to_internal_value(self, data):
        if data is None or data == '':
            return None
        if isinstance(data, str) and data.strip().upper() == 'OWNER':
            return None
        if isinstance(data, EmployeeRole):
            return data
        try:
            return super().to_internal_value(data)
        except Exception:
            pass
        if isinstance(data, str):
            try:
                return EmployeeRole.objects.get(name__iexact=data.strip())
            except EmployeeRole.DoesNotExist:
                pass
        raise serializers.ValidationError(f"Invalid role: '{data}'. Must be a valid Role ID or role name.")


class EmployeeSerializer(serializers.ModelSerializer):
    employeeidnum = serializers.IntegerField(required=False)
    role = FlexibleRoleField(queryset=EmployeeRole.objects.all(), required=False, allow_null=True)
    role_name = serializers.ReadOnlyField()

    class Meta:
        model = Employee
        fields = [
            'id', 'employeeidnum', 'name', 'username', 'email', 'phone',
            'profile_picture', 'house', 'street', 'district', 'state',
            'country', 'pincode', 'address', 'dob', 'date_of_join',
            'blood_group', 'role', 'role_name', 'must_change_password', 'created_at', 'updated_at'
        ]

    def validate_employeeidnum(self, value):
        if value is None:
            return value
        return validate_employee_id_num(value, instance=self.instance)


class CreateEmployeeSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)
    employeeidnum = serializers.IntegerField(required=False, allow_null=True)
    role = FlexibleRoleField(queryset=EmployeeRole.objects.all(), required=False, allow_null=True)

    class Meta:
        model = Employee
        fields = [
            'username', 'name', 'email', 'phone', 'profile_picture',
            'house', 'street', 'district', 'state', 'country', 'pincode',
            'address', 'dob', 'date_of_join', 'blood_group', 'role',
            'password', 'employeeidnum'
        ]

    def validate_employeeidnum(self, value):
        if value is None:
            return value
        return validate_employee_id_num(value, instance=None)

    def validate(self, attrs):
        """
        Enforce that the requesting employee can only assign roles whose
        hierarchy_level is strictly greater than their own.
        Owner can assign any role including OWNER itself.
        """
        request = self.context.get('request')
        role_obj = attrs.get('role')  # None means OWNER role is being assigned

        if request and request.user and request.user.is_authenticated:
            requester = request.user
            if not requester.can_manage_role(role_obj):
                role_label = role_obj.display_name if role_obj else 'Owner'
                raise serializers.ValidationError(
                    {"role": (
                        f"You cannot assign the '{role_label}' role. "
                        "You may only assign roles that are ranked below your own."
                    )}
                )

        return attrs


    def create(self, validated_data):
        password = validated_data.pop('password')
        employee = Employee(**validated_data)
        employee.set_password(password)
        employee.must_change_password = True  # Explicitly set for new employees
        employee.save()
        return employee


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True)

    def validate_new_password(self, value):
        # Length check: Enforces a minimum of 8 characters.
        # Capital letter check: Verifies at least 1 uppercase letter is present.
        # Number check: Verifies at least 1 numeric digit is present.
        # Special character check: Verifies at least 1 non-alphanumeric character is present.
        # Username check: Safe retrieval of the current authenticated user's username from the serializer context, and checking to ensure it is not contained (case-insensitive) in the password.
        
        if len(value) < 8:
            raise serializers.ValidationError("Password must be at least 8 characters long.")
        if not any(char.isupper() for char in value):
            raise serializers.ValidationError("Password must contain at least one uppercase letter.")
        if not any(char.isdigit() for char in value):
            raise serializers.ValidationError("Password must contain at least one number.")
        if not any(not char.isalnum() for char in value):
            raise serializers.ValidationError("Password must contain at least one special character.")
        
        request = self.context.get('request')
        if request and request.user and request.user.is_authenticated:
            username = request.user.username
            if username and username.lower() in value.lower():
                raise serializers.ValidationError("Password cannot contain your username.")
        return value

    def validate(self, attrs):
        if attrs.get('old_password') == attrs.get('new_password'):
            raise serializers.ValidationError(
                {"new_password": "New password cannot be the same as the old password."}
            )
        return attrs


class AdminResetPasswordSerializer(serializers.Serializer):
    new_password = serializers.CharField(required=True, write_only=True)

    def validate_new_password(self, value):
        if len(value) < 8:
            raise serializers.ValidationError("Password must be at least 8 characters long.")
        if not any(char.isupper() for char in value):
            raise serializers.ValidationError("Password must contain at least one uppercase letter.")
        if not any(char.isdigit() for char in value):
            raise serializers.ValidationError("Password must contain at least one number.")
        if not any(not char.isalnum() for char in value):
            raise serializers.ValidationError("Password must contain at least one special character.")
        return value

class CustomTokenObtainPairSerializer(serializers.Serializer):
    token_class = RefreshToken

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["userinfo"] = serializers.CharField(write_only=True)
        self.fields["password"] = serializers.CharField(write_only=True)

    def validate(self, attrs):
        login_value = attrs.get("userinfo")
        password = attrs.get("password")

        if not login_value or not password:
            raise serializers.ValidationError("Both credentials and password are required.")

        try:
            user = Employee.objects.get(
                Q(username=login_value) | Q(email=login_value) | Q(phone=login_value),
                is_deleted=False
            )
        except Employee.DoesNotExist:
            raise AuthenticationFailed("No active account found with the given credentials", "no_active_account")
        except Employee.MultipleObjectsReturned:
            raise AuthenticationFailed("No active account found with the given credentials", "no_active_account")

        if not user.check_password(password):
            raise AuthenticationFailed("No active account found with the given credentials", "no_active_account")

        if not user.is_active:
            raise AuthenticationFailed("No active account found with the given credentials", "no_active_account")

        self.user = user

        # Blacklist all previous outstanding tokens for this user
        from rest_framework_simplejwt.token_blacklist.models import OutstandingToken, BlacklistedToken
        try:
            outstanding_tokens = OutstandingToken.objects.filter(user=self.user)
            for t in outstanding_tokens:
                BlacklistedToken.objects.get_or_create(token=t)
        except Exception as e:
            log_error_to_file(e, self.user.username if self.user else None)

        refresh = self.token_class.for_user(self.user)
        data = {
            "refresh": str(refresh),
            "access": str(refresh.access_token),
        }

        request = self.context.get('request')
        if request:
            # Terminate any existing active sessions for this user
            LoginHistory.objects.filter(employee=self.user, status='active').update(
                status='inactive',
                logout_at=timezone.now()
            )

            # Create new session
            history = LoginHistory.objects.create(
                employee=self.user,
                ip_address=self.get_client_ip(request),
                user_agent=request.META.get('HTTP_USER_AGENT'),
                status='active'
            )
            
            # Blacklist the temporary token created above
            try:
                temp_outstanding = OutstandingToken.objects.filter(user=self.user, jti=refresh['jti']).first()
                if temp_outstanding:
                    BlacklistedToken.objects.get_or_create(token=temp_outstanding)
            except Exception as e:
                log_error_to_file(e, self.user.username if self.user else None)
            
            # Re-generate tokens to include the history_id claim
            refresh = self.token_class.for_user(self.user)
            refresh['history_id'] = str(history.id)
            
            # Update the response data with the new tokens containing the claim
            data['refresh'] = str(refresh)
            data['access'] = str(refresh.access_token)
            
        data['must_change_password'] = self.user.must_change_password
        data['role'] = self.user.role_name
        data['role_id'] = str(self.user.role.id) if self.user.role else None
        data['hierarchy_level'] = self.user.hierarchy_level
        data['name'] = self.user.name
        data['employeeidnum'] = self.user.employeeidnum
        return data

    def get_client_ip(self, request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip

class LoginHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = LoginHistory
        fields = ['id', 'login_at', 'logout_at', 'ip_address', 'user_agent', 'status']

class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField()


class CustomTokenRefreshSerializer(TokenRefreshSerializer):
    def validate(self, attrs):
        refresh = self.token_class(attrs["refresh"])

        user_id = refresh.payload.get(api_settings.USER_ID_CLAIM, None)
        if user_id:
            try:
                user = get_user_model().objects.get(
                    **{api_settings.USER_ID_FIELD: user_id}
                )
            except get_user_model().DoesNotExist:
                raise AuthenticationFailed(
                    self.error_messages["no_active_account"],
                    "no_active_account",
                )

            if not api_settings.USER_AUTHENTICATION_RULE(user):
                raise AuthenticationFailed(
                    self.error_messages["no_active_account"],
                    "no_active_account",
                )

        data = {"access": str(refresh.access_token)}

        if api_settings.ROTATE_REFRESH_TOKENS:
            if api_settings.BLACKLIST_AFTER_ROTATION:
                try:
                    # Attempt to blacklist the given refresh token
                    refresh.blacklist()
                except AttributeError:
                    # If blacklist app not installed, `blacklist` method will
                    # not be present
                    pass

            refresh.set_jti()
            refresh.set_exp()
            refresh.set_iat()
            refresh.outstand()

            data["refresh"] = str(refresh)

        return data


# -----------------------------------------------------------------------
# Role-Based Access Control serializers
# -----------------------------------------------------------------------

PERMISSION_GROUP_FIELDS = [
    'employee_manage',
    'dealers_manage',
    'products_manage',
    'collection_manage',
    'orders_manage',
    'attendance_manage',
    'visit_manage',
    'leads_manage',
    'milage_manage',
]


class EmployeeRoleSerializer(serializers.ModelSerializer):
    """Read + partial-update serializer for EmployeeRole."""

    class Meta:
        model = EmployeeRole
        fields = [
            'id',
            'name',
            'display_name',
            'is_builtin',
            'hierarchy_level',
        ] + PERMISSION_GROUP_FIELDS + ['created_at', 'updated_at']
        read_only_fields = ['id', 'is_builtin', 'created_at', 'updated_at']


class EmployeeRoleCreateSerializer(serializers.ModelSerializer):
    """Creation serializer for new custom roles (Owner only)."""

    class Meta:
        model = EmployeeRole
        fields = ['id', 'name', 'display_name', 'hierarchy_level'] + PERMISSION_GROUP_FIELDS
        read_only_fields = ['id']

    def validate_name(self, value):
        normalized = value.strip().upper().replace(' ', '_')
        if EmployeeRole.objects.filter(name=normalized).exists():
            raise serializers.ValidationError(
                f"A role with name '{normalized}' already exists."
            )
        return normalized

    def validate_hierarchy_level(self, value):
        """
        Custom roles created by Owner may NOT claim level 1 (Owner-reserved).
        Any value >= 2 is acceptable.
        """
        if value < 2:
            raise serializers.ValidationError(
                "Hierarchy level 1 is reserved for the Owner role and cannot be assigned to custom roles."
            )
        return value

    def create(self, validated_data):
        validated_data['is_builtin'] = False
        return super().create(validated_data)

