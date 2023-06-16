import requests
import urllib.parse

from os import environ
from re import fullmatch
from bson import ObjectId
from functools import wraps
from pymongo import MongoClient
from werkzeug.security import check_password_hash
from flask import redirect, render_template, session


# regEx to validate inputs
regEx = {"username": "[A-Za-z0-9._-]{3,16}", "password": "[A-Za-z0-9¡!¿?$+._-]{6,16}"}


# Returns a MongoDB connection utilizing a URL-encoded string connection.
def getMongoConnection(
    mongoDBUsername: str, mongoDBPassword: str, mongoDBDatabaseURL: str
) -> MongoClient:
    connection = MongoClient(
        f"mongodb+srv://{urllib.parse.quote_plus(mongoDBUsername)}:{urllib.parse.quote_plus(mongoDBPassword)}@{urllib.parse.quote_plus(mongoDBDatabaseURL)}/?retryWrites=true&w=majority"
    )
    return connection


def getDbTable(connection: MongoClient, dbName: str, table: str):
    db = connection[dbName]
    table = db[table]
    return table


# If there is a loginId session, it converts it to an ObjectId object. ObjectId it's necessary for querying in MongoDB.
def getLoginId(sessionLoginId: str):
    loginId = None
    if sessionLoginId:
        loginId = ObjectId(sessionLoginId)

    return loginId


def isValidLogin(usersTable, user, password, session):
    # Before consulting anything, it first checks whether the username has the correct syntax or not
    if (
        not fullmatch(regEx["username"], user)
        or not len(user) >= 2
        or not len(user) <= 16
    ):
        return False

    # Again, before consulting anything, the code first checks whether the password have the correct syntax or not
    if fullmatch(regEx["password"], password):
        # Now that we know that the syntax for both username and password are valid, we first consult with the database
        # to find out whether the user exists or not
        userExists = usersTable.find_one({"username": user}, {"hash": 1})

        # If it exists, we compare the password that the user provided with the hashed
        # password stored in the database
        if userExists:
            hashedPassword: str = userExists["hash"]
            isValidPassword: bool = check_password_hash(hashedPassword, password)

            # If the password that the user provided it's the same as the hashed password
            # that we have stored in the database, then we log in the user, and return a
            # valid response
            if isValidPassword:
                session["loginId"] = str(userExists["_id"])

                response = {"isValidLogin": True}
                return response

            # If any of previous checks fails, then we return an invalid response
            else:
                return False
        else:
            return False
    else:
        return False


def login_required(f):
    """
    Decorate routes to require login.

    https://flask.palletsprojects.com/en/1.1.x/patterns/viewdecorators/
    """

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("loginId") is None:
            return redirect("/login")
        return f(*args, **kwargs)

    return decorated_function


# Quote the specified stock symbol.
def lookup(symbol: str) -> dict:
    """Look up quote for symbol."""

    # Contact API
    apiKey = environ.get("API_KEY")
    url = f"https://api.twelvedata.com/quote?symbol={urllib.parse.quote_plus(symbol)}&apikey={urllib.parse.quote_plus(apiKey)}"
    response = requests.get(url)
    response.raise_for_status()

    # Parse response
    quote = response.json()
    if not "status" in quote:
        return {
            "name": quote["name"],
            "price": float(quote["close"]),
            "symbol": quote["symbol"],
        }

    return quote


def usd(value):
    """Format value as USD."""
    return f"${value:,.2f}"
