from flask_wtf import FlaskForm
from wtforms import BooleanField, PasswordField, StringField, SubmitField
from wtforms.validators import DataRequired, Length


class LoginForm(FlaskForm):
    username = StringField(
        "Username",
        validators=[DataRequired(), Length(min=1, max=80)],
        render_kw={"autocomplete": "username"},
    )
    password = PasswordField(
        "Password",
        validators=[DataRequired(), Length(min=12, max=256)],
        render_kw={"autocomplete": "current-password"},
    )
    remember = BooleanField("Keep me signed in on this device")
    submit = SubmitField("Sign in")


class LogoutForm(FlaskForm):
    submit = SubmitField("Sign out")
