import os
import shutil

# Custom apps to clean
apps = ["users", "dealers", "tracking", "sales", "crm", "communication"]
base_dir = os.path.dirname(os.path.abspath(__file__))

print(f"Starting migration cleanup in {base_dir}...")

for app in apps:
    migrations_dir = os.path.join(base_dir, app, "migrations")
    if not os.path.exists(migrations_dir):
        print(f"Skipping {app} - no migrations folder found.")
        continue
    
    deleted_count = 0
    # Clean files inside migrations directory
    for item in os.listdir(migrations_dir):
        item_path = os.path.join(migrations_dir, item)
        # We want to keep ONLY __init__.py and not touch __pycache__ directory
        if item == "__init__.py":
            continue
            
        if os.path.isfile(item_path):
            try:
                os.remove(item_path)
                deleted_count += 1
            except Exception as e:
                print(f"Error removing file {item_path}: {e}")
        elif os.path.isdir(item_path):
            try:
                shutil.rmtree(item_path)
                deleted_count += 1
            except Exception as e:
                print(f"Error removing folder {item_path}: {e}")
                
    print(f"Cleaned {app}/migrations/ - removed {deleted_count} file(s)/folder(s).")

print("Migration cleanup finished successfully!")
