from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, SubmitField, SelectField, IntegerField, DateField
from wtforms.validators import DataRequired, Length, Email, EqualTo, Optional, ValidationError
from models import User, PlanType # Import PlanType
from datetime import date

class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=4, max=80)])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Login')

class AdminLoginForm(FlaskForm):
    username = StringField('Admin Username', validators=[DataRequired()])
    password = PasswordField('Admin Password', validators=[DataRequired()])
    submit = SubmitField('Admin Login')

class UserForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=3, max=80)])
    email = StringField('Email (Optional)', validators=[Optional(), Email(), Length(max=120)])
    plan = SelectField('Plan', choices=[(pt.name, pt.value) for pt in PlanType], validators=[DataRequired()])
    expiry_days = IntegerField('Extend Expiry By (days from today)', validators=[Optional()]) # Or set fixed date
    # Or an absolute expiry_date field:
    # expiry_date = DateField('Expiry Date (YYYY-MM-DD)', format='%Y-%m-%d', validators=[Optional()])

    password = PasswordField('Password (leave blank to keep current)', validators=[Optional(), Length(min=6)])
    confirm_password = PasswordField('Confirm Password', validators=[EqualTo('password', message='Passwords must match')])
    is_active = BooleanField('Active Account', default=True)
    submit = SubmitField('Save User')

    def __init__(self, obj=None, *args, **kwargs):
        super(UserForm, self).__init__(obj=obj, *args, **kwargs)
        if obj and obj.expiry_date:
            # expiry_date field would be pre-filled automatically if it was DateField
            # For expiry_days, it's an extension, so not pre-filled.
            pass

    def validate_username(self, username):
        # When creating a new user or changing username
        # This requires passing the original username if editing
        user = User.query.filter_by(username=username.data).first()
        if hasattr(self, 'obj') and self.obj and self.obj.username == username.data: # Editing existing user, username not changed
            return
        if user:
            raise ValidationError('Username already taken. Please choose a different one.')

    def validate_email(self, email):
        if email.data: # Only validate if email is provided
            user = User.query.filter_by(email=email.data).first()
            if hasattr(self, 'obj') and self.obj and self.obj.email == email.data: # Editing existing user, email not changed
                return
            if user:
                raise ValidationError('Email already registered. Please choose a different one.')

class AdminSettingsForm(FlaskForm):
    maintenance_mode = BooleanField('Maintenance Mode')
    trial_duration_days = IntegerField('Trial Duration (days)', validators=[DataRequired()])
    trial_daily_limit = IntegerField('Trial Daily Request Limit', validators=[DataRequired()])
    submit = SubmitField('Save Settings')