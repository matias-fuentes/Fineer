from os import environ
from re import fullmatch
from datetime import datetime
from dotenv import load_dotenv, find_dotenv
from werkzeug.security import generate_password_hash
from flask import Flask, redirect, render_template, request, session
from api.helpers import (
    getDbTable,
    getMongoConnection,
    getLoginId,
    isValidLogin,
    login_required,
    lookup,
    usd,
)

# Find and load the .env file with the environment variables
load_dotenv(find_dotenv())

# Configure application
app = Flask(__name__)
app.secret_key = environ.get("SECRET_KEY")

# Custom filter
app.jinja_env.filters["usd"] = usd

# Ensure templates are auto-reloaded
app.config["TEMPLATES_AUTO_RELOAD"] = True


# Ensure responses aren't cached
@app.after_request
def after_request(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response


# RegExs to validate inputs
regEx = {"username": "[A-Za-z0-9._-]{3,16}", "password": "[A-Za-z0-9¡!¿?$+._-]{6,16}"}


# Show portfolio of stocks
@app.route("/")
@login_required
def index():
    # MongoDB connection and tables
    connection = getMongoConnection(
        environ.get("MONGODB_USERNAME"),
        environ.get("MONGODB_PASSWORD"),
        environ.get("MONGODB_DATABASE_URL"),
    )
    usersTable = getDbTable(connection, "fineer", "users")
    portfolioTable = getDbTable(connection, "fineer", "portfolio")

    loginId = getLoginId(session.get("loginId"))
    cash = usersTable.find_one({"_id": loginId}, {"cash": 1, "_id": 0})["cash"]

    portfolio = list(
        portfolioTable.find(
            {"userId": loginId}, {"userId": 1, "symbol": 1, "shares": 1}
        )
    )
    connection.close()

    total = cash
    cash = usd(cash)
    quotes = []
    if portfolio:
        for stock in portfolio:
            consultedStock: dict = lookup(stock["symbol"])

            price = float(consultedStock["price"])
            stockTotal = float(price * stock["shares"])
            total += stockTotal

            quote = {
                "symbol": consultedStock["symbol"],
                "name": consultedStock["name"],
                "total": usd(stockTotal),
                "price": usd(price),
                "shares": stock["shares"],
            }
            quotes.append(quote)

        return render_template(
            "portfolio.html",
            cash=cash,
            quotes=quotes,
            loginId=loginId,
            total=usd(total),
            quotesLength=len(quotes),
        )

    total = usd(total)
    return render_template(
        "portfolio.html",
        cash=cash,
        loginId=loginId,
        total=total,
    )


# Buy shares of stock
@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():
    loginId = getLoginId(session.get("loginId"))
    if request.method == "POST":
        symbol = request.form.get("symbol")
        shares = request.form.get("shares")

        if shares.isdigit():
            shares = int(shares)
            quote = lookup(symbol)
            price = round(quote["price"] * shares, 2)

            connection = getMongoConnection(
                environ.get("MONGODB_USERNAME"),
                environ.get("MONGODB_PASSWORD"),
                environ.get("MONGODB_DATABASE_URL"),
            )
            usersTable = getDbTable(connection, "fineer", "users")

            cash = usersTable.find_one({"_id": loginId}, {"cash": 1, "_id": 0})["cash"]
            cash = float(cash)

            if cash >= price and price > 0:
                portfolioTable = getDbTable(connection, "fineer", "portfolio")
                alreadyExists = portfolioTable.find_one(
                    {"symbol": symbol, "userId": loginId}, {"symbol": 1, "shares": 1}
                )

                if not alreadyExists:
                    purchasedShares = {
                        "userId": loginId,
                        "symbol": symbol,
                        "shares": shares,
                    }

                    portfolioTable.insert_one(purchasedShares)
                else:
                    sharesOwned = alreadyExists["shares"]
                    symbolOwned = alreadyExists["symbol"]

                    portfolioTable.update_one(
                        {"userId": loginId, "symbol": symbolOwned},
                        {"$set": {"shares": int(sharesOwned + shares)}},
                        True,
                    )

                usersTable.update_one(
                    {"_id": loginId}, {"$set": {"cash": cash - price}}, True
                )

                now = datetime.now()
                dateTime = now.strftime("%Y-%m-%d %H:%M:%S")
                registeredPurchase = {
                    "userId": loginId,
                    "symbol": symbol,
                    "shares": shares,
                    "price": price,
                    "date": dateTime,
                }

                historyTable = getDbTable(connection, "fineer", "history")
                historyTable.insert_one(registeredPurchase)

                connection.close()
                return redirect("/")

        else:
            errorMessage = "Invalid shares value. Please, try again"
            return render_template("buy.html", errorMessage=errorMessage)

    else:
        return render_template("buy.html", loginId=loginId)


@app.route("/history")
@login_required
def history():
    connection = getMongoConnection(
        environ.get("MONGODB_USERNAME"),
        environ.get("MONGODB_PASSWORD"),
        environ.get("MONGODB_DATABASE_URL"),
    )
    historyTable = getDbTable(connection, "fineer", "history")
    loginId = getLoginId(session.get("loginId"))

    history = list(
        historyTable.find(
            {"userId": loginId},
            {"symbol": 1, "shares": 1, "price": 1, "date": 1, "_id": 0},
        ).sort("id")
    )

    connection.close()
    return render_template("history.html", history=history, loginId=loginId)


@app.route("/login", methods=["GET", "POST"])
def login():
    # Forget any loginId
    session.clear()

    if request.method == "POST":
        user = request.form.get("user")
        password = request.form.get("password")

        connection = getMongoConnection(
            environ.get("MONGODB_USERNAME"),
            environ.get("MONGODB_PASSWORD"),
            environ.get("MONGODB_DATABASE_URL"),
        )
        usersTable = getDbTable(connection, "fineer", "users")

        response = isValidLogin(usersTable, user, password, session)
        connection.close()
        if response == False:
            errorMessage = (
                "Your username and/or password are incorrect. Please, try again."
            )

            return render_template("login.html", errorMessage=errorMessage)
        else:
            return redirect("/")

    return render_template("login.html")


@app.route("/logout")
def logout():
    # Forget any loginId
    session.clear()

    # Redirect user to login form
    return redirect("/")


# Quote entered stock
@app.route("/quote", methods=["GET", "POST"])
@login_required
def quote():
    loginId = getLoginId(session.get("loginId"))
    if request.method == "GET":
        return render_template("quote.html", loginId=loginId)

    else:
        symbol = request.form.get("symbol")

        if not symbol:
            errorMessage = "Invalid symbol. Please, try again"
            return render_template("quote.html", errorMessage=errorMessage)

        stockData = lookup(symbol)
        return render_template(
            "quoted.html",
            name=stockData["name"],
            symbol=stockData["symbol"],
            price=stockData["price"],
            loginId=loginId,
        )


@app.route("/register", methods=["GET", "POST"])
def register():
    # Forget any loginId
    session.clear()

    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        confirmedPassword = request.form.get("password-confirmation")

        # Check if username is valid or not
        if not fullmatch(regEx["username"], username):
            if len(username) < 3 or len(username) > 16:
                errorMessage = "Username must be at least 3 characters, with a maximum of 16 characters."
                return render_template("register.html", errorMessage=errorMessage)

            errorMessage = "Invalid username. Please, use valid special characters (underscore, minus, and periods)."
            return render_template("register.html", errorMessage=errorMessage)

        elif password != confirmedPassword:
            errorMessage = (
                "Password and confirmation does not match. Please, try again."
            )
            return render_template("register.html", errorMessage=errorMessage)

        # Check if password is valid or not
        elif not fullmatch(regEx["password"], password):
            if len(password) < 6 or len(password) > 16:
                errorMessage = "Password must be at least 6 characters, with a maximum of 16 characters."
                return render_template("register.html", errorMessage=errorMessage)

            errorMessage = "Invalid password. Please, use valid special characters."
            return render_template("register.html", errorMessage=errorMessage)

        # Check both if username and/or password already exists. If not, then the account
        # is created
        else:
            connection = getMongoConnection(
                environ.get("MONGODB_USERNAME"),
                environ.get("MONGODB_PASSWORD"),
                environ.get("MONGODB_DATABASE_URL"),
            )
            usersTable = getDbTable(connection, "fineer", "users")

            errorMessage = "The username is already taken. Please, try again or "
            exists = usersTable.find_one(
                {"username": username}, {"username": 1, "_id": 0}
            )

            if exists:
                connection.close()
                return render_template("register.html", errorMessage=errorMessage)

            hashedPassword = generate_password_hash(
                password, method="pbkdf2:sha256", salt_length=8
            )

            # If everything is correct and has passed all the conditions, then we create
            # the user object that we want to insert on the database, and insert it
            userToInsert = {
                "username": username,
                "hash": hashedPassword,
                "cash": 10000,
            }
            usersTable.insert_one(userToInsert)
            loginId = usersTable.find_one({"username": username}, {"_id": 1})["_id"]
            session["loginId"] = str(loginId)
            connection.close()

            return redirect("/")

    return render_template("register.html")


# Sell entered shares of stock
@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    connection = getMongoConnection(
        environ.get("MONGODB_USERNAME"),
        environ.get("MONGODB_PASSWORD"),
        environ.get("MONGODB_DATABASE_URL"),
    )
    portfolioTable = getDbTable(connection, "fineer", "portfolio")
    loginId = getLoginId(session.get("loginId"))

    # ownedSymbols it's a list of objects which each object has a 'symbol' key:
    # [{ "symbol": 'APPL' }, { "symbol": 'MSFT }]
    ownedSymbols = list(
        portfolioTable.find({"userId": loginId}, {"symbol": 1, "_id": 0})
    )

    # With this loop, we remove the unnecesary objects within the ownedSymbols list.
    # At the end, we will have something like this:
    # ['APPL', 'MSFT']
    count = 0
    for symbol in ownedSymbols:
        ownedSymbols[count] = symbol["symbol"]
        count += 1

    if request.method == "POST":
        symbol = request.form.get("symbol")
        soldShares = request.form.get("shares")

        if not soldShares.isdigit():
            errorMessage = "Invalid shares. Please, enter a valid value"
            return render_template(
                "sell.html", errorMessage=errorMessage, ownedSymbols=ownedSymbols
            )

        soldShares = int(soldShares)
        quote = lookup(symbol)

        if "status" in quote and quote["status"] == "error":
            errorMessage = (
                "The stock symbol specified it's incorrect. Please, try again."
            )
            return render_template(
                "sell.html", errorMessage=errorMessage, ownedSymbols=ownedSymbols
            )

        price = round(quote["price"] * soldShares, 2)

        usersTable = getDbTable(connection, "fineer", "users")
        cash: float = usersTable.find_one({"_id": loginId}, {"cash": 1, "_id": 0})[
            "cash"
        ]

        alreadyExists = portfolioTable.find_one(
            {"symbol": symbol, "userId": loginId}, {"symbol": 1, "shares": 1}
        )

        ownedShares = alreadyExists["shares"]
        stockId = alreadyExists["_id"]
        if not alreadyExists:
            connection.close()
            errorMessage = (
                "The connection with the database was lost. Please, try again"
            )
            return render_template(
                "sell.html", errorMessage=errorMessage, ownedSymbols=ownedSymbols
            )
        elif soldShares > ownedShares:
            connection.close()
            errorMessage = "Invalid shares. Shares entered are greater than what you own. Please, try again"
            return render_template(
                "sell.html", errorMessage=errorMessage, ownedSymbols=ownedSymbols
            )
        elif soldShares < 1:
            connection.close()
            errorMessage = "Invalid value. Please, try again"
            return render_template(
                "sell.html", errorMessage=errorMessage, ownedSymbols=ownedSymbols
            )
        else:
            if soldShares == ownedShares:
                portfolioTable.delete_one({"_id": stockId})
            else:
                shares = ownedShares - soldShares
                portfolioTable.update_one(
                    {"_id": stockId},
                    {"$set": {"shares": shares}},
                    True,
                )

            cash = cash + price
            usersTable.update_one({"_id": loginId}, {"$set": {"cash": cash}})

            now = datetime.now()
            dateTime = now.strftime("%Y-%m-%d %H:%M:%S")
            historyTable = getDbTable(connection, "fineer", "history")

            transaction = {
                "userId": loginId,
                "symbol": symbol,
                "shares": int(-soldShares),
                "price": price,
                "date": dateTime,
            }
            historyTable.insert_one(transaction)
            connection.close()

            return redirect("/")

    connection.close()
    return render_template("sell.html", ownedSymbols=ownedSymbols, loginId=loginId)
