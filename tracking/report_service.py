from datetime import date
from decimal import Decimal
from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from tracking.models import Attendance, Visit
from sales.models import Order, OrderItem, Collection, MonthlyTarget


def get_attendance_for_date(employee, target_date=None):
    """
    Fetches the attendance record for the given employee and date.
    Defaults to today's date if not provided.
    """
    if target_date is None:
        target_date = timezone.localdate()
    attendance = Attendance.objects.filter(employee=employee, date=target_date).first()
    if not attendance:
        raise ValidationError(
            {"attendance": f"No attendance check-in found for employee '{employee.username}' on {target_date}. Please check in first."}
        )
    return attendance, target_date


def calculate_sod_data(employee, target_date=None, attendance=None, require_attendance=True):
    """
    Calculates Start of Day (SOD) report metrics for an employee on target_date:
    1. Monthly target (from MonthlyTarget).
    2. Month-to-date achieved actuals (orders except rejected, collections except failed, visits count).
    3. Balance targets remaining for the month.
    4. Today's targets submitted in SOD.
    5. Returns both structured dictionary and formatted text string.
    """
    if target_date is None:
        target_date = timezone.localdate()

    if attendance is None:
        if require_attendance:
            attendance, _ = get_attendance_for_date(employee, target_date)
        else:
            attendance = Attendance.objects.filter(employee=employee, date=target_date).first()

    month_start = date(target_date.year, target_date.month, 1)
    month_name = target_date.strftime("%B")
    date_str = target_date.strftime("%d/%m/%Y")
    officer_name = employee.name if employee.name else employee.username

    # 1. Fetch Monthly Target
    m_target = MonthlyTarget.objects.filter(
        employee=employee,
        year=target_date.year,
        month=target_date.month,
    ).first()

    month_sales_target = m_target.sales_target if m_target else Decimal("0.00")
    month_collection_target = m_target.collection_target if m_target else Decimal("0.00")
    month_visits_target = m_target.visits_target if m_target else 0

    # 2. Month-to-date achieved (from 1st of month to target_date)
    orders_mtd = Order.objects.filter(
        employee=employee,
        created_at__date__gte=month_start,
        created_at__date__lte=target_date,
    ).exclude(status="rejected")
    till_now_sales = orders_mtd.aggregate(total=Sum("total_amount"))["total"] or Decimal("0.00")

    collections_mtd = Collection.objects.filter(
        employee=employee,
        created_at__date__gte=month_start,
        created_at__date__lte=target_date,
    ).exclude(status="failed")
    till_now_collection = collections_mtd.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

    till_now_visits = Visit.objects.filter(
        employee=employee,
        created_at__date__gte=month_start,
        created_at__date__lte=target_date,
    ).count()

    # 3. Balance targets
    balance_sales_target = max(Decimal("0.00"), month_sales_target - till_now_sales)
    balance_collection_target = max(Decimal("0.00"), month_collection_target - till_now_collection)
    balance_visits_target = max(0, month_visits_target - till_now_visits)

    # 4. Today's target from attendance
    today_sales_target = attendance.sod_sales_target or Decimal("0.00") if attendance else Decimal("0.00")
    today_collection_target = attendance.sod_collection_target or Decimal("0.00") if attendance else Decimal("0.00")
    today_visits_target = attendance.sod_visits_target or 0 if attendance else 0
    today_market_plan = attendance.sod_market_plan or "" if attendance else ""

    structured_data = {
        "officer_name": officer_name,
        "date": date_str,
        "month_name": month_name,
        "month_sales_target": f"{month_sales_target:.2f}",
        "till_now_sales": f"{till_now_sales:.2f}",
        "balance_sales_target": f"{balance_sales_target:.2f}",
        "today_sales_target": f"{today_sales_target:.2f}",
        "month_collection_target": f"{month_collection_target:.2f}",
        "till_now_collection": f"{till_now_collection:.2f}",
        "balance_collection_target": f"{balance_collection_target:.2f}",
        "today_collection_target": f"{today_collection_target:.2f}",
        "month_visits_target": month_visits_target,
        "till_now_visits": till_now_visits,
        "balance_visits_target": balance_visits_target,
        "today_visits_target": today_visits_target,
        "today_market_plan": today_market_plan,
    }

    formatted_report = (
        f"Sir,\n"
        f"{officer_name} - {date_str}\n"
        f"{month_name} \n\n\n"
        f"{month_name} month sales target: {structured_data['month_sales_target']}\n\n"
        f"Till now sales : {structured_data['till_now_sales']} ({month_name} 1st to today)\n\n"
        f"Balance {month_name} sales target: {structured_data['balance_sales_target']}\n\n"
        f"Today sales target : {structured_data['today_sales_target']} \n\n\n"
        f"{month_name} month collection: {structured_data['month_collection_target']}\n\n"
        f"Till now collection : {structured_data['till_now_collection']} ({month_name} 1st to today)\n\n"
        f"Balance {month_name} collection targets : {structured_data['balance_collection_target']}\n\n"
        f"Today collection Target: {structured_data['today_collection_target']} \n\n\n"
        f"My counter visit target  plan  : {month_visits_target} visits\n\n"
        f"This month till date (achieved)visited : {till_now_visits}\n\n"
        f"Today visit plan target : {today_visits_target}\n\n"
        f"Balance {month_name} counter target  : {balance_visits_target}\n\n\n"
        f"Today market visit plan : {today_market_plan}"
    )

    structured_data["formatted_report"] = formatted_report
    return structured_data


def calculate_eod_data(employee, target_date=None, attendance=None, require_attendance=True):
    """
    Calculates End of Day (EOD) report metrics for an employee on target_date:
    1. Opening, closing, total travel KM from Attendance.
    2. Today's orders created and product summary.
    3. Today's collections.
    4. Today's visited counters count and visited areas.
    5. Tomorrow visit plan area.
    6. Returns both structured dictionary and formatted text string.
    """
    if target_date is None:
        target_date = timezone.localdate()

    if attendance is None:
        if require_attendance:
            attendance, _ = get_attendance_for_date(employee, target_date)
        else:
            attendance = Attendance.objects.filter(employee=employee, date=target_date).first()

    month_name = target_date.strftime("%B")
    date_str = target_date.strftime("%d/%m/%Y")
    officer_name = employee.name if employee.name else employee.username

    opening_km = attendance.start_km if attendance else None
    closing_km = attendance.end_km if attendance else None
    travel_km = attendance.total_km if attendance else None
    if travel_km is None and closing_km is not None and opening_km is not None:
        travel_km = round(closing_km - opening_km, 2)

    # Today's orders
    today_orders = Order.objects.filter(
        employee=employee,
        created_at__date=target_date,
    ).exclude(status="rejected")

    today_orders_amount = today_orders.aggregate(total=Sum("total_amount"))["total"] or Decimal("0.00")
    
    # Generate order summary e.g. [13T(steels)] or [Order total: 35000.00]
    order_items = OrderItem.objects.filter(order__in=today_orders).select_related("product")
    if order_items.exists():
        items_summary = ", ".join([f"{item.quantity}{item.product.unit}({item.product.name})" for item in order_items])
        orders_summary = f"[{items_summary}]"
    elif today_orders.exists():
        orders_summary = f"[{today_orders_amount:.2f}/-]"
    else:
        orders_summary = "Nil"

    # Today's collections
    today_collections = Collection.objects.filter(
        employee=employee,
        created_at__date=target_date,
    ).exclude(status="failed")
    today_collection_amount = today_collections.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

    # Today's visits
    today_visits = Visit.objects.filter(
        employee=employee,
        created_at__date=target_date,
    ).select_related("dealer", "client")
    visited_counters_count = today_visits.count()

    # Visited areas: use attendance.eod_visited_areas or infer from visited dealers
    visited_areas = attendance.eod_visited_areas if attendance else ""
    if not visited_areas and today_visits.exists():
        areas = []
        for v in today_visits:
            dealer = v.dealer or v.client
            if dealer:
                loc = dealer.street or dealer.district or dealer.shop_name
                if loc and loc not in areas:
                    areas.append(loc)
        visited_areas = ", ".join(areas) if areas else "Nil"
    elif not visited_areas:
        visited_areas = "Nil"

    tomorrow_plan = attendance.eod_tomorrow_plan or "" if attendance else ""

    structured_data = {
        "officer_name": officer_name,
        "date": date_str,
        "month_name": month_name,
        "visited_areas": visited_areas,
        "opening_km": opening_km,
        "closing_km": closing_km,
        "travel_km": travel_km,
        "today_orders_amount": f"{today_orders_amount:.2f}",
        "orders_summary": orders_summary,
        "today_collection_amount": f"{today_collection_amount:.2f}",
        "visited_counters_count": visited_counters_count,
        "tomorrow_plan": tomorrow_plan,
    }

    opening_km_display = f"{int(opening_km) if opening_km == int(opening_km) else opening_km}" if opening_km is not None else "Not set"
    closing_km_display = f"{int(closing_km) if closing_km == int(closing_km) else closing_km}" if closing_km is not None else "Not checked out"
    travel_km_display = f"{int(travel_km) if travel_km == int(travel_km) else travel_km}" if travel_km is not None else "0"

    formatted_report = (
        f"EOD (Evening ) report :\n"
        f"Name of the officer {officer_name} \n"
        f"{date_str}\n"
        f"{month_name} Month\n\n\n"
        f"Today visited area : {visited_areas} \n\n"
        f"Opening km : {opening_km_display}\n"
        f"Closing km   : {closing_km_display}\n\n"
        f"Today travel km : {travel_km_display}\n\n\n"
        f"Today order : {orders_summary}\n\n"
        f"Today collection : {structured_data['today_collection_amount']}/-\n\n"
        f"Today visited counter : {visited_counters_count}\n\n"
        f"Tomorrow visit plan area : {tomorrow_plan}"
    )

    structured_data["formatted_report"] = formatted_report
    return structured_data
