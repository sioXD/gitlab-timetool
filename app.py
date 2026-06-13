from flask import Flask, render_template, jsonify, request, send_from_directory
from dotenv import load_dotenv
import os
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime, timedelta
from Epic import Epic
from Issue import Issue
from timetracker import accumulateEpicTree
from collections import defaultdict
import requests
import json
import traceback
from pathlib import Path
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from google import genai
import threading

load_dotenv()

app = Flask(__name__)

def _parse_datetime(date_str, tz=None):
    if not date_str:
        return None
    if date_str.endswith('Z'):
        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
    elif '+' in date_str or date_str.count('-') > 2:
        dt = datetime.fromisoformat(date_str)
    else:
        dt = datetime.fromisoformat(date_str).replace(tzinfo=tz or datetime.now().astimezone().tzinfo)
    if dt.tzinfo is None and tz:
        dt = dt.replace(tzinfo=tz)
    return dt


def _safe_parse_datetime(date_str, tz=None):
    try:
        return _parse_datetime(date_str, tz)
    except Exception:
        return None

# Configure logging
if not os.path.exists('logs'):
    os.makedirs('logs')

file_handler = RotatingFileHandler('logs/app.log', maxBytes=10240000, backupCount=10)
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
))
file_handler.setLevel(logging.INFO)
app.logger.addHandler(file_handler)
app.logger.setLevel(logging.INFO)
app.logger.info('GitLab Time Tracking Dashboard startup')

# Initialize scheduler for automated reports
scheduler = BackgroundScheduler()
scheduler.start()

# Schedule weekly report generation (every Tuesday at 8:00 AM)
scheduler.add_job(
    func=lambda: generate_weekly_report(),
    trigger=CronTrigger(day_of_week='tue', hour=8, minute=0),
    id='weekly_report',
    name='Generate weekly project status report',
    replace_existing=True
)

# Global variables for data
csv_rows = []
users = []
labels = []
epic_tree = None

# Progress tracking
_load_progress = {"phase": "", "pct": 0, "msg": "", "loading": False, "error": None}
_load_lock = threading.Lock()

def _update_progress(phase, pct, msg=None):
    with _load_lock:
        _load_progress["phase"] = phase
        _load_progress["pct"] = pct
        _load_progress["msg"] = msg or phase
        _load_progress["loading"] = phase not in ("done", "error")

def _load_data_background(token, group_path, epic_id):
    """Run load_data in background thread and update progress."""
    global csv_rows, users, labels, epic_tree
    try:
        _update_progress("start", 0, "Starting data load...")
        import timetracker
        timetracker.users = []
        timetracker.labels = []
        timetracker.csv_rows = []

        epic_tree = accumulateEpicTree(
            group_path=group_path,
            epic_iid=epic_id,
            token=token,
            progress_callback=_update_progress
        )
        epic_tree.accumulateTimes()

        users = sorted(list(set(timetracker.users)))
        labels = sorted(list(set(timetracker.labels)))

        _update_progress("rows", 98, "Building data rows...")
        csv_rows = []

        def build_rows(e):
            parentId = None if (e.parent == None) else e.parent.id
            row = {
                "Typ": e.type,
                "Titel": e.title,
                "IID": e.id,
                "Parent IID": parentId,
                "Zeitaufwand (h)": round(e.hoursSpent, 2),
                "gesch. Zeitaufwand (h)": round(e.hoursEstimate, 2)
            }
            if e.type == "issue":
                user_percentages = e.getUserPercentagesByTime()
                for user in users:
                    row[user] = round(user_percentages.get(user, 0), 4)
                for label in labels:
                    row[label] = e.hasLabel(label)
                row["createdAt"] = getattr(e, 'createdAt', None)
                row["state"] = getattr(e, 'state', 'opened')
            else:
                for user in users:
                    row[user] = 0
                for label in labels:
                    row[label] = False
                row["createdAt"] = None
                row["state"] = None
            csv_rows.append(row)
            for child in e.children:
                build_rows(child)

        build_rows(epic_tree)
        app.logger.info(f"Data loaded successfully: {len(csv_rows)} items, {len(users)} users, {len(labels)} labels")
        _update_progress("done", 100, f"Loaded {len(csv_rows)} items")
    except Exception as ex:
        app.logger.error(f"Background load error: {ex}")
        _update_progress("error", 0, str(ex))

def load_data(force_refresh=False, token=None, group_path=None, epic_id=None):
    global _load_progress
    with _load_lock:
        is_loading = _load_progress["loading"]
    if (force_refresh or epic_tree is None) and not is_loading:
        app.logger.info(f"Triggering background load - force_refresh={force_refresh}, epic_tree={'None' if epic_tree is None else 'exists'}")
        GROUP_FULL_PATH = group_path if group_path is not None else os.getenv("GROUP_FULL_PATH")
        EPIC_IID = epic_id if epic_id is not None else os.getenv("EPIC_ROOT_ID")
        TOKEN = token if token is not None else os.getenv("TOKEN")
        if not GROUP_FULL_PATH or not EPIC_IID or not TOKEN:
            raise ValueError("Missing required parameters: TOKEN, GROUP_FULL_PATH, and EPIC_ROOT_ID")
        t = threading.Thread(target=_load_data_background, args=(TOKEN, GROUP_FULL_PATH, EPIC_IID), daemon=True)
        t.start()
    return csv_rows

def filter_data_by_date(days=None):
    """Filter time data by date range using spentAt from timelogs"""
    if days is None:
        cutoff_date = None
    else:
        cutoff_date = datetime.now(datetime.now().astimezone().tzinfo) - timedelta(days=days)
    
    filtered_rows = []
    
    def build_filtered_rows(e):
        parentId = None if (e.parent == None) else e.parent.id
        
        if e.type == "issue":
            # Filter timelogs by date using 'Datum' field which contains spentAt
            filtered_hours_spent = 0
            filtered_user_times = {}
            
            try:
                for user, time_entries in e.userTimeMap.items():
                    user_total = 0
                    for entry in time_entries:
                        entry_date = _safe_parse_datetime(entry['Datum'], cutoff_date.tzinfo if cutoff_date else None)
                        if entry_date is None:
                            user_total += entry['Zeit(Std)']
                        elif cutoff_date is None or entry_date >= cutoff_date:
                            user_total += entry['Zeit(Std)']

                    if user_total > 0:
                        filtered_user_times[user] = user_total
                        filtered_hours_spent += user_total
            except Exception as ex:
                print(f"Error filtering dates for issue {e.title}: {ex}")
                # If filtering fails, include all time
                for user, time_entries in e.userTimeMap.items():
                    user_total = sum(entry['Zeit(Std)'] for entry in time_entries)
                    filtered_user_times[user] = user_total
                    filtered_hours_spent += user_total
            
            # Calculate percentages
            user_percentages = {}
            if filtered_hours_spent > 0:
                for user in users:
                    if user in filtered_user_times:
                        user_percentages[user] = filtered_user_times[user] / filtered_hours_spent
                    else:
                        user_percentages[user] = 0
            else:
                for user in users:
                    user_percentages[user] = 0
            
            row = {
                "Typ": e.type,
                "Titel": e.title,
                "IID": e.id,
                "Parent IID": parentId,
                "Zeitaufwand (h)": round(filtered_hours_spent, 2),
                "gesch. Zeitaufwand (h)": round(e.hoursEstimate, 2),
                "createdAt": getattr(e, 'createdAt', None),
                "state": getattr(e, 'state', 'opened')  # Status hinzufügen
            }
            
            for user in users:
                row[user] = round(user_percentages.get(user, 0), 4)
            for label in labels:
                row[label] = e.hasLabel(label)
                
        else:  # Epic
            row = {
                "Typ": e.type,
                "Titel": e.title,
                "IID": e.id,
                "Parent IID": parentId,
                "Zeitaufwand (h)": 0,
                "gesch. Zeitaufwand (h)": round(e.hoursEstimate, 2),
                "createdAt": None,
                "state": None  # Epics haben keinen Status
            }
            for user in users:
                row[user] = 0
            for label in labels:
                row[label] = False
        
        filtered_rows.append(row)
        
        # Process children first
        for child in e.children:
            build_filtered_rows(child)
        
        # Sum up children's times for epics (from filtered_rows that have been added)
        if e.type == "epic":
            child_rows = [r for r in filtered_rows if r.get("Parent IID") == e.id]
            total_child_time = sum(r["Zeitaufwand (h)"] for r in child_rows)
            row["Zeitaufwand (h)"] = round(total_child_time, 2)
            
            # Also calculate user percentages for epics based on children
            if total_child_time > 0:
                for user in users:
                    user_time_in_children = sum(
                        r["Zeitaufwand (h)"] * r.get(user, 0) 
                        for r in child_rows
                    )
                    row[user] = round(user_time_in_children / total_child_time if total_child_time > 0 else 0, 4)
    
    if epic_tree:
        build_filtered_rows(epic_tree)
    
    return filtered_rows

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/progress")
def get_progress():
    with _load_lock:
        return jsonify(dict(_load_progress))

@app.route("/api/data")
def get_data():
    try:
        app.logger.info(f"API /api/data called - args: {dict(request.args)}")
        days = request.args.get('days', None)
        days = int(days) if days else None
        start_date = request.args.get('start_date', None)
        end_date = request.args.get('end_date', None)
        refresh = request.args.get('refresh', 'false').lower() == 'true'

        group_full_path = os.getenv("GROUP_FULL_PATH", "")
        repository_name = os.getenv("REPOSITORY_NAME", "")

        if refresh:
            load_data(force_refresh=True)
        elif epic_tree is None:
            load_data(force_refresh=False)

        # If still loading, return status
        with _load_lock:
            still_loading = _load_progress["loading"]
            load_error = _load_progress["error"]
        if still_loading and not csv_rows:
            return jsonify({"success": True, "loading": True, "data": [], "users": [], "labels": []})
        if load_error and not csv_rows:
            return jsonify({"success": False, "error": load_error}), 500

        if start_date and end_date:
            data = filter_data_by_date_range(start_date, end_date)
        elif days:
            data = filter_data_by_date(days)
        else:
            data = csv_rows

        issues = [d for d in data if d['Typ'] == 'issue']
        total_spent = sum(d['Zeitaufwand (h)'] for d in issues)
        total_estimated = sum(d['gesch. Zeitaufwand (h)'] for d in issues)

        user_stats = {}
        for user in users:
            user_total = sum(d['Zeitaufwand (h)'] * d.get(user, 0) for d in issues)
            user_stats[user] = round(user_total, 2)

        label_stats = {}
        for label in labels:
            label_issues = [d for d in issues if d.get(label, False)]
            label_stats[label] = {
                'count': len(label_issues),
                'hours': round(sum(d['Zeitaufwand (h)'] for d in label_issues), 2)
            }

        target_matrix_labels = ["Entwurf", "Implementation & Test", "Projektmanagement", "Requirements Engineering"]

        if start_date and end_date:
            creation_stats = calculate_creation_stats_date_range(issues, start_date, end_date)
            cfd_stats = calculate_cfd_stats_date_range(issues, start_date, end_date)
            label_timeline_stats = calculate_label_timeline_stats_date_range(
                issues, target_matrix_labels, start_date, end_date
            )
        else:
            creation_stats = calculate_creation_stats(issues, days)
            cfd_stats = calculate_cfd_stats(issues, days)
            label_timeline_stats = calculate_label_timeline_stats(
                issues, target_matrix_labels, days
            )

        user_label_matrix = calculate_user_label_matrix(issues, target_matrix_labels, users)

        return jsonify({
            "success": True,
            "data": data,
            "users": users,
            "labels": labels,
            "group_path": group_full_path,
            "repository_name": repository_name,
            "stats": {
                "total_spent": round(total_spent, 2),
                "total_estimated": round(total_estimated, 2),
                "user_stats": user_stats,
                "label_stats": label_stats,
                "creation_stats": creation_stats,
                "cfd_stats": cfd_stats,
                "label_timeline_stats": label_timeline_stats,
                "user_label_matrix": user_label_matrix
            }
        })
    except Exception as e:
        app.logger.error(f"Error in /api/data: {str(e)}\n{traceback.format_exc()}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500

def filter_data_by_date_range(start_date_str, end_date_str):
    """Filter time data by specific date range"""
    try:
        start_date = datetime.fromisoformat(start_date_str).replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = datetime.fromisoformat(end_date_str).replace(hour=23, minute=59, second=59, microsecond=999999)
        
        # Make timezone aware
        if start_date.tzinfo is None:
            start_date = start_date.replace(tzinfo=datetime.now().astimezone().tzinfo)
        if end_date.tzinfo is None:
            end_date = end_date.replace(tzinfo=datetime.now().astimezone().tzinfo)
    except Exception as e:
        print(f"Error parsing date range: {e}")
        return csv_rows
    
    filtered_rows = []
    
    def build_filtered_rows(e):
        parentId = None if (e.parent == None) else e.parent.id
        
        if e.type == "issue":
            filtered_hours_spent = 0
            filtered_user_times = {}
            
            try:
                for user, time_entries in e.userTimeMap.items():
                    user_total = 0
                    for entry in time_entries:
                        entry_date = _safe_parse_datetime(entry['Datum'], start_date.tzinfo)
                        if entry_date is None:
                            user_total += entry['Zeit(Std)']
                        elif start_date <= entry_date <= end_date:
                            user_total += entry['Zeit(Std)']

                    if user_total > 0:
                        filtered_user_times[user] = user_total
                        filtered_hours_spent += user_total
            except Exception as ex:
                print(f"Error filtering date range for issue {e.title}: {ex}")
                for user, time_entries in e.userTimeMap.items():
                    user_total = sum(entry['Zeit(Std)'] for entry in time_entries)
                    filtered_user_times[user] = user_total
                    filtered_hours_spent += user_total
            
            user_percentages = {}
            if filtered_hours_spent > 0:
                for user in users:
                    if user in filtered_user_times:
                        user_percentages[user] = filtered_user_times[user] / filtered_hours_spent
                    else:
                        user_percentages[user] = 0
            else:
                for user in users:
                    user_percentages[user] = 0
            
            row = {
                "Typ": e.type,
                "Titel": e.title,
                "IID": e.id,
                "Parent IID": parentId,
                "Zeitaufwand (h)": round(filtered_hours_spent, 2),
                "gesch. Zeitaufwand (h)": round(e.hoursEstimate, 2),
                "createdAt": getattr(e, 'createdAt', None),
                "state": getattr(e, 'state', 'opened')
            }
            
            for user in users:
                row[user] = round(user_percentages.get(user, 0), 4)
            for label in labels:
                row[label] = e.hasLabel(label)
                
        else:  # Epic
            row = {
                "Typ": e.type,
                "Titel": e.title,
                "IID": e.id,
                "Parent IID": parentId,
                "Zeitaufwand (h)": 0,
                "gesch. Zeitaufwand (h)": round(e.hoursEstimate, 2),
                "createdAt": None,
                "state": None
            }
            for user in users:
                row[user] = 0
            for label in labels:
                row[label] = False
        
        filtered_rows.append(row)
        
        for child in e.children:
            build_filtered_rows(child)
        
        if e.type == "epic":
            child_rows = [r for r in filtered_rows if r.get("Parent IID") == e.id]
            total_child_time = sum(r["Zeitaufwand (h)"] for r in child_rows)
            row["Zeitaufwand (h)"] = round(total_child_time, 2)
            
            if total_child_time > 0:
                for user in users:
                    user_time_in_children = sum(
                        r["Zeitaufwand (h)"] * r.get(user, 0) 
                        for r in child_rows
                    )
                    row[user] = round(user_time_in_children / total_child_time if total_child_time > 0 else 0, 4)
    
    if epic_tree:
        build_filtered_rows(epic_tree)
    
    return filtered_rows

def calculate_creation_stats_date_range(issues, start_date_str, end_date_str):
    """Calculate issue creation statistics for specific date range"""
    start_date = datetime.fromisoformat(start_date_str).replace(tzinfo=datetime.now().astimezone().tzinfo)
    end_date = datetime.fromisoformat(end_date_str).replace(tzinfo=datetime.now().astimezone().tzinfo)
    
    weekly_stats = defaultdict(lambda: defaultdict(int))
    
    for issue in issues:
        created_at = issue.get('createdAt')
        if not created_at:
            continue
        
        try:
            created_date = _safe_parse_datetime(created_at, start_date.tzinfo)
            if created_date is None or not (start_date <= created_date <= end_date):
                continue

            week_start = created_date - timedelta(days=created_date.weekday())
            week_label = week_start.strftime('%Y-%m-%d')

            max_user = None
            max_percentage = 0
            for user in users:
                percentage = issue.get(user, 0)
                if percentage > max_percentage:
                    max_percentage = percentage
                    max_user = user

            if max_user:
                weekly_stats[week_label][max_user] += 1
            else:
                weekly_stats[week_label]['Unbekannt'] += 1

        except Exception:
            continue
    
    sorted_weeks = sorted(weekly_stats.keys())
    result = {
        'weeks': sorted_weeks,
        'user_data': {}
    }
    
    for user in users + ['Unbekannt']:
        result['user_data'][user] = [weekly_stats[week].get(user, 0) for week in sorted_weeks]
    
    result['user_data'] = {k: v for k, v in result['user_data'].items() if sum(v) > 0}
    
    return result

def calculate_cfd_stats_date_range(issues, start_date_str, end_date_str):
    """Calculate CFD statistics for specific date range based on actual work dates"""
    from collections import defaultdict
    
    start_date = datetime.fromisoformat(start_date_str).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=datetime.now().astimezone().tzinfo)
    end_date = datetime.fromisoformat(end_date_str).replace(hour=23, minute=59, second=59, microsecond=999999, tzinfo=datetime.now().astimezone().tzinfo)
    
    # Track which issues had work on which days
    issue_work_dates = defaultdict(set)  # issue_id -> set of dates with work
    issue_status = {}  # issue_id -> current status
    
    if epic_tree:
        def process_issue(e):
            if e.type == "issue":
                issue_id = e.id
                state = e.state if hasattr(e, 'state') else 'opened'
                issue_status[issue_id] = state
                
                if hasattr(e, 'userTimeMap'):
                    for user, time_entries in e.userTimeMap.items():
                        for entry in time_entries:
                            entry_date = _safe_parse_datetime(entry['Datum'], start_date.tzinfo)
                            if entry_date is not None and start_date <= entry_date <= end_date:
                                issue_work_dates[issue_id].add(entry_date.strftime('%Y-%m-%d'))
            
            for child in e.children:
                process_issue(child)
        
        process_issue(epic_tree)
    
    # Build daily status counts
    daily_status = {}
    day = start_date
    
    while day <= end_date:
        day_label = day.strftime('%Y-%m-%d')
        
        # Track which issues we've seen on or before this day
        issues_seen = set()
        todo_count = 0
        in_progress_count = 0
        done_count = 0
        
        for issue_id, work_dates in issue_work_dates.items():
            # Check if this issue has any work up to this day
            has_work_until_today = any(d <= day_label for d in work_dates)
            
            if has_work_until_today:
                issues_seen.add(issue_id)
                state = issue_status.get(issue_id, 'opened')
                
                # Check if work was done on this specific day
                work_on_this_day = day_label in work_dates
                
                if state == 'closed':
                    done_count += 1
                elif work_on_this_day or any(d <= day_label for d in work_dates):
                    # If work was done on this day or before, it's in progress
                    in_progress_count += 1
                else:
                    todo_count += 1
        
        daily_status[day_label] = {
            'todo': todo_count,
            'in_progress': in_progress_count,
            'done': done_count,
            'total': len(issues_seen)
        }
        
        day += timedelta(days=1)
    
    sorted_dates = sorted(daily_status.keys())
    
    result = {
        'dates': sorted_dates,
        'todo': [daily_status[d]['todo'] for d in sorted_dates],
        'in_progress': [daily_status[d]['in_progress'] for d in sorted_dates],
        'done': [daily_status[d]['done'] for d in sorted_dates],
        'total': [daily_status[d]['total'] for d in sorted_dates]
    }
    
    return result

def calculate_creation_stats(issues, days=None):
    """Calculate issue creation statistics by time period"""
    
    if days is None:
        cutoff_date = None
    else:
        cutoff_date = datetime.now(datetime.now().astimezone().tzinfo) - timedelta(days=days)
    
    # Group issues by week and creator
    weekly_stats = defaultdict(lambda: defaultdict(int))
    
    for issue in issues:
        created_at = issue.get('createdAt')
        if not created_at:
            continue
        
        try:
            tz = cutoff_date.tzinfo if cutoff_date else None
            created_date = _safe_parse_datetime(created_at, tz)
            if created_date is None or (cutoff_date is not None and created_date < cutoff_date):
                continue

            week_start = created_date - timedelta(days=created_date.weekday())
            week_label = week_start.strftime('%Y-%m-%d')

            max_user = None
            max_percentage = 0
            for user in users:
                percentage = issue.get(user, 0)
                if percentage > max_percentage:
                    max_percentage = percentage
                    max_user = user

            if max_user:
                weekly_stats[week_label][max_user] += 1
            else:
                weekly_stats[week_label]['Unbekannt'] += 1

        except Exception:
            continue
    
    # Convert to sorted list format
    sorted_weeks = sorted(weekly_stats.keys())
    result = {
        'weeks': sorted_weeks,
        'user_data': {}
    }
    
    for user in users + ['Unbekannt']:
        result['user_data'][user] = [weekly_stats[week].get(user, 0) for week in sorted_weeks]
    
    # Remove users with no issues created
    result['user_data'] = {k: v for k, v in result['user_data'].items() if sum(v) > 0}
    
    return result

def calculate_cfd_stats(issues, days=None):
    """Calculate Cumulative Flow Diagram data - issues by status over time based on actual work dates"""
    from collections import defaultdict
    
    # Determine date range
    if days is None:
        all_dates = []
        if epic_tree:
            def collect_dates(e):
                if e.type == "issue" and hasattr(e, 'userTimeMap'):
                    for user, time_entries in e.userTimeMap.items():
                        for entry in time_entries:
                            entry_date = _safe_parse_datetime(entry['Datum'])
                            if entry_date is not None:
                                all_dates.append(entry_date)
                for child in e.children:
                    collect_dates(child)
            collect_dates(epic_tree)

        if all_dates:
            cutoff_date = min(all_dates).replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            cutoff_date = datetime.now(datetime.now().astimezone().tzinfo) - timedelta(days=30)
            cutoff_date = cutoff_date.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        cutoff_date = datetime.now(datetime.now().astimezone().tzinfo) - timedelta(days=days)
        cutoff_date = cutoff_date.replace(hour=0, minute=0, second=0, microsecond=0)
    
    end_date = datetime.now(datetime.now().astimezone().tzinfo).replace(hour=23, minute=59, second=59)
    
    # Track which issues had work on which days
    issue_work_dates = defaultdict(set)  # issue_id -> set of dates with work
    issue_status = {}  # issue_id -> current status
    
    if epic_tree:
        def process_issue(e):
            if e.type == "issue":
                issue_id = e.id
                state = e.state if hasattr(e, 'state') else 'opened'
                issue_status[issue_id] = state

                if hasattr(e, 'userTimeMap'):
                    for user, time_entries in e.userTimeMap.items():
                        for entry in time_entries:
                            entry_date = _safe_parse_datetime(entry['Datum'], end_date.tzinfo)
                            if entry_date is not None and cutoff_date <= entry_date <= end_date:
                                issue_work_dates[issue_id].add(entry_date.strftime('%Y-%m-%d'))

            for child in e.children:
                process_issue(child)

        process_issue(epic_tree)
    
    # Build daily status counts
    daily_status = {}
    day = cutoff_date
    
    while day <= end_date:
        day_label = day.strftime('%Y-%m-%d')
        
        # Track which issues we've seen on or before this day
        issues_seen = set()
        todo_count = 0
        in_progress_count = 0
        done_count = 0
        
        for issue_id, work_dates in issue_work_dates.items():
            # Check if this issue has any work up to this day
            has_work_until_today = any(d <= day_label for d in work_dates)
            
            if has_work_until_today:
                issues_seen.add(issue_id)
                state = issue_status.get(issue_id, 'opened')
                
                # Check if work was done on this specific day
                work_on_this_day = day_label in work_dates
                
                if state == 'closed':
                    done_count += 1
                elif work_on_this_day or any(d <= day_label for d in work_dates):
                    # If work was done on this day or before, it's in progress
                    in_progress_count += 1
                else:
                    todo_count += 1
        
        daily_status[day_label] = {
            'todo': todo_count,
            'in_progress': in_progress_count,
            'done': done_count,
            'total': len(issues_seen)
        }
        
        day += timedelta(days=1)
    
    # Sort by date
    sorted_dates = sorted(daily_status.keys())
    
    result = {
        'dates': sorted_dates,
        'todo': [daily_status[d]['todo'] for d in sorted_dates],
        'in_progress': [daily_status[d]['in_progress'] for d in sorted_dates],
        'done': [daily_status[d]['done'] for d in sorted_dates],
        'total': [daily_status[d]['total'] for d in sorted_dates]
    }
    
    return result

def calculate_label_timeline_stats(issues, target_labels, days=None):
    """Calculate timeline statistics for specific labels based on actual time logging dates"""
    from collections import defaultdict
    
    if days is None:
        cutoff_date = None
    else:
        cutoff_date = datetime.now(datetime.now().astimezone().tzinfo) - timedelta(days=days)
    
    # Get date range from epic_tree time entries
    if cutoff_date is None:
        all_dates = []
        if epic_tree:
            def collect_dates(e):
                if e.type == "issue" and hasattr(e, 'userTimeMap'):
                    for user, time_entries in e.userTimeMap.items():
                        for entry in time_entries:
                            entry_date = _safe_parse_datetime(entry['Datum'])
                            if entry_date is not None:
                                all_dates.append(entry_date)
                for child in e.children:
                    collect_dates(child)
            collect_dates(epic_tree)

        if all_dates:
            cutoff_date = min(all_dates)
        else:
            cutoff_date = datetime.now(datetime.now().astimezone().tzinfo) - timedelta(days=30)
    
    # Create daily timeline
    current_date = cutoff_date.replace(hour=0, minute=0, second=0, microsecond=0)
    end_date = datetime.now(datetime.now().astimezone().tzinfo).replace(hour=23, minute=59, second=59)
    
    daily_label_hours = defaultdict(lambda: {label: 0 for label in target_labels})
    
    # Iterate through epic_tree and accumulate time based on actual logging dates
    if epic_tree:
        def process_issue(e):
            if e.type == "issue":
                # Check which labels this issue has
                issue_labels = [label for label in target_labels if e.hasLabel(label)]
                
                if issue_labels and hasattr(e, 'userTimeMap'):
                    for user, time_entries in e.userTimeMap.items():
                        for entry in time_entries:
                            entry_date = _safe_parse_datetime(entry['Datum'], current_date.tzinfo)
                            if entry_date is not None and current_date <= entry_date <= end_date:
                                day_label = entry_date.strftime('%Y-%m-%d')
                                time_hours = entry['Zeit(Std)']
                                time_per_label = time_hours / len(issue_labels)
                                for label in issue_labels:
                                    daily_label_hours[day_label][label] += time_per_label
            
            for child in e.children:
                process_issue(child)
        
        process_issue(epic_tree)
    
    # Create cumulative timeline
    day = current_date
    cumulative_hours = {label: 0 for label in target_labels}
    sorted_dates = []
    cumulative_data = defaultdict(list)
    
    while day <= end_date:
        day_label = day.strftime('%Y-%m-%d')
        sorted_dates.append(day_label)
        
        # Add today's hours to cumulative
        for label in target_labels:
            cumulative_hours[label] += daily_label_hours[day_label].get(label, 0)
            cumulative_data[label].append(round(cumulative_hours[label], 2))
        
        day += timedelta(days=1)
    
    result = {
        'dates': sorted_dates,
        'labels': target_labels,
        'data': {label: cumulative_data[label] for label in target_labels}
    }
    
    return result

def calculate_label_timeline_stats_date_range(issues, target_labels, start_date_str, end_date_str):
    """Calculate timeline statistics for specific labels in a date range based on actual time logging dates"""
    from collections import defaultdict
    
    start_date = datetime.fromisoformat(start_date_str).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=datetime.now().astimezone().tzinfo)
    end_date = datetime.fromisoformat(end_date_str).replace(hour=23, minute=59, second=59, microsecond=999999, tzinfo=datetime.now().astimezone().tzinfo)
    
    daily_label_hours = defaultdict(lambda: {label: 0 for label in target_labels})
    
    # Iterate through epic_tree and accumulate time based on actual logging dates
    if epic_tree:
        def process_issue(e):
            if e.type == "issue":
                issue_labels = [label for label in target_labels if e.hasLabel(label)]

                if issue_labels and hasattr(e, 'userTimeMap'):
                    for user, time_entries in e.userTimeMap.items():
                        for entry in time_entries:
                            entry_date = _safe_parse_datetime(entry['Datum'], start_date.tzinfo)
                            if entry_date is not None and start_date <= entry_date <= end_date:
                                day_label = entry_date.strftime('%Y-%m-%d')
                                time_hours = entry['Zeit(Std)']
                                time_per_label = time_hours / len(issue_labels)
                                for label in issue_labels:
                                    daily_label_hours[day_label][label] += time_per_label

            for child in e.children:
                process_issue(child)

        process_issue(epic_tree)
    
    # Create cumulative timeline
    day = start_date
    cumulative_hours = {label: 0 for label in target_labels}
    sorted_dates = []
    cumulative_data = defaultdict(list)
    
    while day <= end_date:
        day_label = day.strftime('%Y-%m-%d')
        sorted_dates.append(day_label)
        
        # Add today's hours to cumulative
        for label in target_labels:
            cumulative_hours[label] += daily_label_hours[day_label].get(label, 0)
            cumulative_data[label].append(round(cumulative_hours[label], 2))
        
        day += timedelta(days=1)
    
    result = {
        'dates': sorted_dates,
        'labels': target_labels,
        'data': {label: cumulative_data[label] for label in target_labels}
    }
    
    return result

def calculate_user_label_matrix(issues, target_labels, users):
    """Calculate matrix of time spent by user per label"""
    # Initialize matrix
    matrix = {user: {label: 0.0 for label in target_labels} for user in users}
    
    for issue in issues:
        # Find which target labels this issue has
        active_labels = [label for label in target_labels if issue.get(label, False)]
        
        if not active_labels:
            continue
            
        total_time = issue.get('Zeitaufwand (h)', 0)
        if total_time <= 0:
            continue
            
        # Calculate time per label (distribute equally if multiple labels)
        for user in users:
            user_percentage = issue.get(user, 0)
            if user_percentage > 0:
                user_time = total_time * user_percentage
                time_per_label = user_time / len(active_labels)
                
                for label in active_labels:
                    matrix[user][label] += time_per_label
                    
    # Round values
    for user in matrix:
        for label in matrix[user]:
            matrix[user][label] = round(matrix[user][label], 2)
            
    return matrix

def _collect_epic_hierarchy(e, indent=0):
    """Build a readable tree string from the epic tree for the prompt."""
    lines = []
    prefix = "  " * indent
    if e.type == "epic":
        spent_str = f"{round(e.hoursSpent, 1)}h" if e.hoursSpent else "-"
        est_str = f"{round(e.hoursEstimate, 1)}h" if e.hoursEstimate else "-"
        lines.append(f"{prefix}- {e.title} (IID: {e.id}, spent: {spent_str}, estimated: {est_str})")
    for child in e.children:
        lines.extend(_collect_epic_hierarchy(child, indent + 1))
    return lines


def generate_weekly_report():
    """Generate weekly project status report using Google Gemini API"""
    try:
        load_data(force_refresh=True)

        reports_dir = Path("reports")
        reports_dir.mkdir(exist_ok=True)

        last_week_data = filter_data_by_date(7)
        issues = [d for d in last_week_data if d['Typ'] == 'issue']

        total_spent = round(sum(d['Zeitaufwand (h)'] for d in issues), 2)
        total_estimated = round(sum(d['gesch. Zeitaufwand (h)'] for d in issues), 2)

        user_stats = {}
        for user in users:
            user_total = round(sum(d['Zeitaufwand (h)'] * d.get(user, 0) for d in issues), 2)
            if user_total > 0:
                user_stats[user] = user_total

        label_stats = {}
        for label in labels:
            label_issues = [d for d in issues if d.get(label, False)]
            if label_issues:
                label_stats[label] = {
                    'count': len(label_issues),
                    'hours': round(sum(d['Zeitaufwand (h)'] for d in label_issues), 2)
                }

        top_issues = sorted(issues, key=lambda x: x['Zeitaufwand (h)'], reverse=True)[:10]

        cutoff_date = datetime.now(datetime.now().astimezone().tzinfo) - timedelta(days=7)
        issues_opened_in_period = 0
        issues_closed_in_period = 0

        all_data = csv_rows
        all_issues = [d for d in all_data if d['Typ'] == 'issue']
        active_iids = {d['IID'] for d in issues}

        for issue in all_issues:
            created_at = issue.get('createdAt')
            if created_at:
                created_date = _safe_parse_datetime(created_at, cutoff_date.tzinfo)
                if created_date is not None and created_date >= cutoff_date:
                    issues_opened_in_period += 1

            if issue.get('state') == 'closed' and issue.get('IID') in active_iids:
                issues_closed_in_period += 1

        target_matrix_labels = ["Entwurf", "Implementation & Test", "Projektmanagement", "Requirements Engineering"]
        user_label_matrix = calculate_user_label_matrix(issues, target_matrix_labels, users)

        epic_lines = _collect_epic_hierarchy(epic_tree) if epic_tree else []

        top_issues_detail = []
        for issue in top_issues:
            labels_str = ", ".join(l for l in labels if issue.get(l, False))
            top_issues_detail.append(f"- #{issue['IID']} {issue['Titel']} | {issue['Zeitaufwand (h)']}h | Labels: {labels_str or '-'}")

        week_label = f"KW {datetime.now().isocalendar()[1]}, {datetime.now().year}"
        date_range_str = f"{(datetime.now() - timedelta(days=7)).strftime('%d.%m.%Y')} - {datetime.now().strftime('%d.%m.%Y')}"

        user_stats_lines = "\n".join(f"  - {user}: {hours}h" for user, hours in sorted(user_stats.items(), key=lambda x: -x[1]))
        label_stats_lines = "\n".join(f"  - {label}: {v['hours']}h ({v['count']} Issues)" for label, v in sorted(label_stats.items(), key=lambda x: -x[1]['hours']))
        matrix_lines = "\n".join(
            f"  - {user}: " + ", ".join(f"{label}={round(v,1)}h" for label, v in sorted(m.items()) if v)
            for user, m in sorted(user_label_matrix.items())
        )
        epic_hierarchy_str = "\n".join(epic_lines)

        prompt = f"""Du bist ein erfahrener Projektleiter. Erstelle einen professionellen, detaillierten Projektstatusreport im HTML-Format.

## Projektkontext
Das Projekt ist eine Lernplattform mit folgenden Epics (Baumstruktur mit aufgewendeter/geschätzter Zeit):
{epic_hierarchy_str}

## Berichtszeitraum
{date_range_str} ({week_label})

## Kennzahlen
- Gesamtzeit (Berichtszeitraum): {total_spent}h
- Gesamtschätzung (Projekt): {total_estimated}h
- Fortschritt: {round(total_spent/total_estimated*100,1) if total_estimated else 0}%
- Offene Issues: {len(all_issues) - len([i for i in all_issues if i.get('state') == 'closed'])} (gesamt)
- Geschlossene Issues: {len([i for i in all_issues if i.get('state') == 'closed'])} (gesamt)
- Im Zeitraum geöffnet: {issues_opened_in_period}
- Im Zeitraum geschlossen: {issues_closed_in_period}

## Zeitverteilung nach Mitarbeitern
{user_stats_lines}

## Zeitverteilung nach Labels/Kategorien
{label_stats_lines}

## Matrix: Mitarbeiter x Überkategorien (Stunden)
{matrix_lines}

## Top 10 Issues nach Zeitaufwand
{chr(10).join(top_issues_detail)}

## Formatierungsvorgaben
- Erstelle einen vollständigen, eigenständigen HTML-Bericht mit DOCTYPE, head und body.
- Style alles mit INLINE-CSS (kein separates <style>, jedes Element bekommt style="...").
- Farbschema: Teal/Türkis (#0891b2 Primär, #06b6d4 Akzent, #ecfeff Hintergrund).
- Schrift: 'Segoe UI', system-ui, -apple-system, sans-serif.
- Verwende weiße Karten (card) mit abgerundeten Ecken und sanften Schatten.
- Baue für jede Metrik eine optische Karte mit Icon und großem Zahlenwert.
- Zeige die Mitarbeiter-Zeit als horizontale Balken (div mit prozentualer Breite, teal gefüllt).
- Die Top-Issues sollen als Liste mit farbigen Labels erscheinen.
- Füge eine Tabelle für die Mitarbeiter-x-Kategorie-Matrix ein.
- Verwende für Kategorie-Labels kleine Badges mit Hintergrundfarbe.

## Struktur (Reihenfolge)
1. Header: Berichtszeitraum, Projektname
2. Executive Summary (3-4 Sätze mit Einordnung der Zahlen)
3. Kennzahlen-Karten (4-6 Karten nebeneinander)
4. Mitarbeiter-Zeit (Balkendiagramm)
5. Kategorie-Zeit (Tabelle oder Balken)
6. Matrix: Mitarbeiter x Überkategorien
7. Top 10 Issues
8. Zusammenfassung & Ausblick (2-3 Sätze mit Handlungsempfehlungen)

Wichtig: Gib NUR das HTML zurück, ohne Markdown-Umschließung. Kein ```html vorher oder nachher."""

        client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

        try:
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt
            )
            app.logger.info(f"Gemini response received")
        except Exception as e:
            app.logger.error(f"Error in AI response: {e}")
            return {'success': False, 'error': f"Gemini API error: {e}"}

        html_report = response.text

        if html_report.startswith('```html'):
            html_report = html_report.replace('```html', '').replace('```', '').strip()
        elif html_report.startswith('```'):
            html_report = html_report.replace('```', '').strip()

        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        filename = f"report_{timestamp}.html"
        filepath = reports_dir / filename

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(html_report)

        app.logger.info(f"Weekly report generated: {filename}")
        print(f"[OK] Weekly report generated: {filename}")
        return {
            'success': True,
            'filename': filename,
            'filepath': str(filepath),
            'data': {
                'week': week_label,
                'date_range': date_range_str,
                'total_hours': total_spent,
                'total_estimated': total_estimated,
                'user_stats': user_stats,
                'top_issues': [
                    {'title': d['Titel'], 'iid': d['IID'], 'hours': d['Zeitaufwand (h)']}
                    for d in top_issues
                ],
                'total_issues': len(all_issues),
                'closed_issues': len([i for i in all_issues if i.get('state') == 'closed']),
                'issues_opened_in_period': issues_opened_in_period,
                'issues_closed_in_period': issues_closed_in_period
            }
        }

    except Exception as e:
        app.logger.error(f"Error generating weekly report: {str(e)}\n{traceback.format_exc()}")
        print(f"[ERROR] Weekly report generation: {e}")
        traceback.print_exc()
        return {'success': False, 'error': str(e)}

@app.route("/api/generate-report", methods=['POST'])
def api_generate_report():
    app.logger.info("API /api/generate-report called")
    try:
        result = generate_weekly_report()
        return jsonify(result)
    except Exception as e:
        app.logger.error(f"Error in /api/generate-report: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route("/api/reports")
def list_reports():
    """List all available reports"""
    try:
        app.logger.info("API /api/reports called")
        reports_dir = Path("reports")
        if not reports_dir.exists():
            return jsonify({'success': True, 'reports': []})
        
        reports = []
        for file in sorted(reports_dir.glob("report_*.html"), reverse=True):
            reports.append({
                'filename': file.name,
                'created': datetime.fromtimestamp(file.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
                'size': file.stat().st_size
            })
        
        return jsonify({'success': True, 'reports': reports})
    except Exception as e:
        app.logger.error(f"Error listing reports: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route("/reports/<filename>")
def serve_report(filename):
    """Serve a specific report file"""
    try:
        app.logger.info(f"Serving report: {filename}")
        reports_dir = Path("reports")
        return send_from_directory(reports_dir, filename)
    except Exception as e:
        app.logger.error(f"Error serving report {filename}: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 404

if __name__ == "__main__":
    app.run(debug=True)
