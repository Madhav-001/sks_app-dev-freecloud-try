from django.db.models import Q
from datetime import datetime


def filter_notifications(queryset, query_params):
    """
    Applies filtering, searching, and ordering to notifications queryset.
    """
    # Filtering by type
    notif_type = query_params.get('notification_type')
    if notif_type:
        queryset = queryset.filter(notification_type=notif_type)

    # Filtering by priority
    priority = query_params.get('priority')
    if priority:
        queryset = queryset.filter(priority=priority.upper())

    # Filtering by is_read
    is_read_str = query_params.get('is_read')
    if is_read_str is not None:
        is_read = is_read_str.lower() in ('true', '1')
        queryset = queryset.filter(is_read=is_read)

    # Search query
    search = query_params.get('search')
    if search:
        queryset = queryset.filter(
            Q(title__icontains=search) | Q(body__icontains=search)
        )

    # Date range filtering (from_date, to_date)
    from_date = query_params.get('from_date')
    if from_date:
        try:
            from_dt = datetime.strptime(from_date, "%d:%m:%Y").date()
            queryset = queryset.filter(created_at__date__gte=from_dt)
        except ValueError:
            pass

    # Ordering
    ordering = query_params.get('ordering', '-created_at')
    # Sanitize ordering
    allowed_ordering = ('created_at', '-created_at', 'priority', '-priority', 'title', '-title')
    if ordering not in allowed_ordering:
        ordering = '-created_at'
    queryset = queryset.order_by(ordering)

    return queryset
