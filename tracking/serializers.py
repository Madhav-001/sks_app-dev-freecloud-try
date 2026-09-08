from rest_framework import serializers
from .models import Attendance, Visit, Milage


class AttendanceStartSerializer(serializers.ModelSerializer):
    image = serializers.ImageField(source='start_image')
    time = serializers.TimeField(source='start_time', format='%H:%M:%S', input_formats=['%H:%M:%S', '%H:%M'])
    latitude = serializers.FloatField(source='start_latitude')
    longitude = serializers.FloatField(source='start_longitude')

    class Meta:
        model = Attendance
        fields = ['image', 'start_km', 'date', 'time', 'latitude', 'longitude']



class AttendanceEndSerializer(serializers.ModelSerializer):
    end_image = serializers.ImageField()
    end_km = serializers.IntegerField()
    date = serializers.DateField(required=False)
    time = serializers.TimeField(source='end_time', format='%H:%M:%S', input_formats=['%H:%M:%S', '%H:%M'])
    latitude = serializers.FloatField(source='end_latitude')
    longitude = serializers.FloatField(source='end_longitude')

    class Meta:
        model = Attendance
        fields = ['end_image', 'end_km', 'date', 'time', 'latitude', 'longitude']


class AttendanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Attendance
        fields = '__all__'


class AttendanceMonthlySerializer(serializers.ModelSerializer):
    """Returns minimal attendance details for the employee attendance page."""
    id = serializers.UUIDField(read_only=True)
    date = serializers.DateField(format='%Y-%m-%d')
    start_time = serializers.SerializerMethodField()
    end_time = serializers.SerializerMethodField()
    total_time = serializers.SerializerMethodField()
    total_km = serializers.SerializerMethodField()

    class Meta:
        model = Attendance
        fields = ['id', 'date', 'start_time', 'end_time', 'total_time', 'total_km', 'auto_checkout']

    def get_start_time(self, obj):
        return obj.start_time.strftime('%H:%M:%S') if obj.start_time else None

    def get_end_time(self, obj):
        return obj.end_time.strftime('%H:%M:%S') if obj.end_time else None

    def get_total_time(self, obj):
        if obj.total_time is None:
            return None
        total_seconds = int(obj.total_time.total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f'{hours:02d}:{minutes:02d}:{seconds:02d}'

    def get_total_km(self, obj):
        return int(obj.total_km) if obj.total_km is not None else None


class VisitSerializer(serializers.ModelSerializer):
    visit_id = serializers.UUIDField(source='id', read_only=True)
    image = serializers.ImageField(source='gps_image')
    time = serializers.TimeField(format='%H:%M:%S', input_formats=['%H:%M:%S', '%H:%M'], required=False, allow_null=True)
    type = serializers.ChoiceField(choices=Visit.TYPE_CHOICES)
    latitude = serializers.CharField()
    longitude = serializers.CharField()
    created_at = serializers.DateTimeField(format='%Y-%m-%d %H:%M:%S', read_only=True)
    updated_at = serializers.DateTimeField(format='%Y-%m-%d %H:%M:%S', read_only=True)

    # attendance_id links the visit to a check-in record so the backend can
    # determine the trip origin for distance calculation. Required field on creation.
    attendance_id = serializers.PrimaryKeyRelatedField(
        queryset=Attendance.objects.all(),
        required=True,
        allow_null=False,
    )

    # Auto-calculated by the view — never accepted from user input.
    travelled_km = serializers.FloatField(read_only=True)

    class Meta:
        model = Visit
        fields = [
            'visit_id',
            'type',
            'dealer',
            'client',
            'image',
            'time',
            'latitude',
            'longitude',
            'attendance_id',
            'travelled_km',
            'collection',
            'order',
            'created_at',
            'updated_at',
        ]
        extra_kwargs = {'employee': {'read_only': True}}

    def validate(self, attrs):
        visit_type = attrs.get('type')
        dealer = attrs.get('dealer')
        client = attrs.get('client')

        if visit_type == 'Dealer':
            if dealer is None:
                raise serializers.ValidationError({'dealer': 'dealer_id is required when type is Dealer.'})
            if client is not None:
                raise serializers.ValidationError({'client': 'client must be null when type is Dealer.'})

        elif visit_type == 'Client':
            if client is None:
                raise serializers.ValidationError({'client': 'client_id is required when type is Client.'})
            if dealer is not None:
                raise serializers.ValidationError({'dealer': 'dealer must be null when type is Client.'})

        return attrs


class VisitBulkSyncSerializer(serializers.ModelSerializer):
    """Used for JSON bulk-sync where images are uploaded separately."""
    gps_image = serializers.ImageField(required=False)

    # Auto-calculated — read-only in responses but writable in bulk-sync
    # payloads so the client can pre-fill if it already computed locally.
    travelled_km = serializers.FloatField(required=False, allow_null=True)

    class Meta:
        model = Visit
        fields = '__all__'
        extra_kwargs = {'employee': {'read_only': True}}


# ---------------------------------------------------------------------------
# Milage serializer
# ---------------------------------------------------------------------------

class MilageSerializer(serializers.ModelSerializer):
    """
    Read serializer for the daily cumulative mileage summary.

    `return_to_home` is populated at check-out.
    `total_distance_travelled` is the running cumulative total updated in
    real-time after every visit.
    """
    employee_id = serializers.UUIDField(source='employee.id', read_only=True)
    employee_name = serializers.SerializerMethodField()
    attendance_id = serializers.UUIDField(
        source='attendance_id.id',
        read_only=True,
        allow_null=True,
    )
    date = serializers.DateField(format='%Y-%m-%d')
    return_to_home = serializers.FloatField()
    total_distance_travelled = serializers.FloatField()
    updated_at = serializers.DateTimeField(format='%Y-%m-%d %H:%M:%S', read_only=True)

    class Meta:
        model = Milage
        fields = [
            'id',
            'employee_id',
            'employee_name',
            'attendance_id',
            'date',
            'return_to_home',
            'total_distance_travelled',
            'updated_at',
        ]

    def get_employee_name(self, obj):
        emp = obj.employee
        return emp.name if getattr(emp, 'name', None) else emp.username


# ---------------------------------------------------------------------------
# Admin — daily mileage report serializer
# ---------------------------------------------------------------------------

class AdminDailyMilageSerializer(serializers.ModelSerializer):
    """
    Per-employee daily mileage row for the admin daily report.

    Fields returned:
      employee_id              – employee UUID
      employee_name            – display name (name or username)
      employee_role            – role string (e.g. 'SALESMAN')
      date                     – the working date
      total_distance_travelled – cumulative GPS-route distance for the day (km)
      return_to_home           – last-visit → checkout leg distance (km)
      attendance_total_km      – odometer-based total from Attendance.total_km
                                 (null if the employee hasn't checked out yet)
      checked_out              – True when Attendance.end_km is populated
      attendance_id            – UUID of the linked Attendance record (nullable)
      updated_at               – last time the mileage record was updated
    """
    employee_id   = serializers.UUIDField(source='employee.id', read_only=True)
    employee_name = serializers.SerializerMethodField()
    employee_role = serializers.CharField(source='employee.role_name', read_only=True)
    date          = serializers.DateField(format='%Y-%m-%d')

    # GPS-route cumulative totals (from the Milage table)
    total_distance_travelled = serializers.FloatField()
    return_to_home           = serializers.FloatField()

    # Odometer-based total from the linked Attendance record (null if not checked out)
    attendance_total_km = serializers.SerializerMethodField()
    checked_out         = serializers.SerializerMethodField()

    attendance_id = serializers.UUIDField(
        source='attendance_id.id',
        read_only=True,
        allow_null=True,
    )
    updated_at = serializers.DateTimeField(format='%Y-%m-%d %H:%M:%S', read_only=True)

    class Meta:
        model = Milage
        fields = [
            'employee_id',
            'employee_name',
            'employee_role',
            'date',
            'total_distance_travelled',
            'return_to_home',
            'attendance_total_km',
            'checked_out',
            'attendance_id',
            'updated_at',
        ]

    def get_employee_name(self, obj):
        emp = obj.employee
        return emp.name if getattr(emp, 'name', None) else emp.username

    def get_attendance_total_km(self, obj):
        """Return odometer total_km from the linked Attendance, or null."""
        att = obj.attendance_id  # FK object (already select_related in the view)
        if att is None:
            return None
        return att.total_km  # null until checkout

    def get_checked_out(self, obj):
        """True when the employee has already checked out for the day."""
        att = obj.attendance_id
        if att is None:
            return False
        return att.end_km is not None


# ---------------------------------------------------------------------------
# Admin — Salesman Visit Count serializers
# ---------------------------------------------------------------------------

class AdminSalesmanDailyVisitBreakdownSerializer(serializers.Serializer):
    """Daily visit breakdown per salesman."""
    date = serializers.DateField(format='%Y-%m-%d')
    total_visits = serializers.IntegerField()
    dealer_visits = serializers.IntegerField()
    client_visits = serializers.IntegerField()


class AdminSalesmanVisitCountItemSerializer(serializers.Serializer):
    """Visit count statistics for a single salesman."""
    employee_id = serializers.UUIDField()
    employeeidnum = serializers.IntegerField()
    name = serializers.CharField()
    username = serializers.CharField()
    phone = serializers.CharField(allow_blank=True)
    role = serializers.CharField()
    profile_picture = serializers.CharField(allow_null=True)
    total_visits = serializers.IntegerField()
    dealer_visits = serializers.IntegerField()
    client_visits = serializers.IntegerField()
    daily_breakdown = AdminSalesmanDailyVisitBreakdownSerializer(many=True)


class AdminSalesmanVisitCountResponseSerializer(serializers.Serializer):
    """Top-level response structure for Admin Salesman Visit Count."""
    filter_type = serializers.CharField()
    start_date = serializers.DateField(format='%Y-%m-%d')
    end_date = serializers.DateField(format='%Y-%m-%d')
    total_salesmen = serializers.IntegerField()
    total_visits = serializers.IntegerField()
    total_dealer_visits = serializers.IntegerField()
    total_client_visits = serializers.IntegerField()
    results = AdminSalesmanVisitCountItemSerializer(many=True)
