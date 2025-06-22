from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date, timedelta
import enum
import os # <--- Ensure this import is present at the top

db = SQLAlchemy()

class PlanType(enum.Enum):
    TRIAL = "Trial"
    SINGLE = "Single Target"
    MULTI = "Multi Target"

    def __str__(self):
        return self.value

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)
    plan = db.Column(db.Enum(PlanType, name='plantype', create_type=False), default=PlanType.TRIAL, nullable=False) # Changed create_type
    expiry_date = db.Column(db.Date, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    requests_today = db.Column(db.Integer, default=0)
    last_request_date = db.Column(db.Date, nullable=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_expired(self):
        if self.expiry_date and self.expiry_date < date.today():
            return True
        return False

    def __repr__(self):
        return f'<User {self.username} - Plan: {self.plan.value}>'

class AdminSetting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False)
    value = db.Column(db.String(200), nullable=False)
    description = db.Column(db.String(255), nullable=True)

    def __repr__(self):
        return f'<AdminSetting {self.key}={self.value}>'

    @classmethod
    def get(cls, key_name, default=None):
        setting = cls.query.filter_by(key=key_name).first()
        if setting:
            if setting.value.lower() == "true": return True
            if setting.value.lower() == "false": return False
            try: return int(setting.value)
            except ValueError: pass
            return setting.value
        return default

    @classmethod
    def set(cls, key_name, value, description=None):
        setting = cls.query.filter_by(key=key_name).first()
        str_value = str(value)
        if setting:
            if setting.value != str_value: # Only update if value changed
                setting.value = str_value
        else:
            setting = cls(key=key_name, value=str_value, description=description)
            db.session.add(setting)
        # Commit should happen after all settings are processed, or if creating a new one
        # For simplicity here, we commit, but this can be optimized
        db.session.commit()
        return setting

def initialize_default_settings():
    """
    Initializes default admin settings if they don't exist.
    This function should be called within an application context.
    """
    defaults = {
        "maintenance_mode": (os.getenv("INITIAL_MAINTENANCE_MODE", "False") == "True", "Enable maintenance mode (users cannot login)"),
        "trial_duration_days": (int(os.getenv("INITIAL_TRIAL_DURATION_DAYS", "3")), "Default duration for trial accounts in days"),
        "trial_daily_limit": (int(os.getenv("INITIAL_TRIAL_DAILY_LIMIT", "10")), "Max single crash requests per day for trial users")
    }
    all_settings_exist = True
    for key in defaults.keys():
        if AdminSetting.query.filter_by(key=key).first() is None:
            all_settings_exist = False
            break # Found one missing, no need to check further for this logic branch

    if not all_settings_exist:
        print("INFO: Initializing default admin settings...")
        for key, (value, desc) in defaults.items():
            # More robust set: check if it exists before trying to create
            existing_setting = AdminSetting.query.filter_by(key=key).first()
            if not existing_setting:
                AdminSetting.set(key, value, desc) # .set will add and commit
            # If you want to update existing ones to default from .env (less common for this func name):
            # else:
            #    AdminSetting.set(key, value, desc) # this would overwrite db with .env defaults
        print("INFO: Default admin settings initialization complete.")
    else:
        print("INFO: Default admin settings already exist, skipping initialization.")