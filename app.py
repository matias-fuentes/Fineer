import mysql.connector.pooling
import os

envVars = os.environ
pool = mysql.connector.pooling.MySQLConnectionPool(
    pool_name=envVars.get('poolName'),
    pool_reset_session=True,
    pool_size=4,
    host=envVars.get('host'),
    port=3306,
    user=envVars.get('user'),
    password=envVars.get('password'),
    db=envVars.get('db')
)

from helpers import apology, login_required, lookup, usd
from flask import Flask, redirect, render_template, request, session
from werkzeug.exceptions import default_exceptions, HTTPException, InternalServerError
from werkzeug.security import check_password_hash, generate_password_hash
from datetime import datetime

# Configure application
app = Flask(__name__)
app.secret_key = envVars.get('secretKey')

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


@app.route("/")
@login_required
def index():
    connection = pool.get_connection()
    cursor = connection.cursor()

    """Show portfolio of stocks"""
    cash = cursor.execute(f"SELECT cash FROM users WHERE id = {session['user_id']}")
    cash = cursor.fetchone()
    cash = cash[0]

    portfolio = cursor.execute(f"SELECT * FROM portfolio WHERE userId = {session['user_id']}")
    portfolio = cursor.fetchall()
    connection.close()

    total = float(cash)
    cash = usd(cash)
    quotes = []
    count = 0
    for stock in portfolio:
        symbol = stock[2]
        quotes.append(lookup(symbol))

        price = quotes[count]['price']
        shares = stock[3]
        stockTotal = price * shares
        total += stockTotal
        quotes[count]['total'] = usd(stockTotal)
        quotes[count]['price'] = usd(price)
        quotes[count]['shares'] = shares
        count += 1

    total = usd(total)
    return render_template("portfolio.html", cash=cash, portfolio=portfolio, portfLength=len(portfolio), quotes=quotes, total=total)


@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():
    """Buy shares of stock"""
    if request.method == "POST":
        symbol = request.form.get('symbol')
        shares = request.form.get('shares')

        if shares.isdigit():
            shares = int(shares)
            quote = lookup(symbol)
            if quote is None:
                return apology("The symbol entered is invalid, or the connection with the database was lost. Please, try again")
            price = round(quote['price'] * shares, 2)

            connection = pool.get_connection()
            cursor = connection.cursor()

            cash = cursor.execute(f"SELECT cash FROM users WHERE id = {session['user_id']}")
            cash = cursor.fetchone()
            cash = float(cash[0])
            if cash >= price and price > 0:
                alreadyExists = cursor.execute(
                    f"SELECT id, symbol, shares FROM portfolio WHERE (symbol = '{symbol}' AND userId = {session['user_id']})")
                alreadyExists = cursor.fetchall()

                if len(alreadyExists) == 0:
                    cursor.execute(f"INSERT INTO portfolio (userId, symbol, shares) VALUES ({session['user_id']}, '{symbol}', {shares})")
                    connection.commit()
                else:
                    sharesPurchased = alreadyExists[0][2]
                    symbolPurchased = alreadyExists[0][1]
                    cursor.execute(f"UPDATE portfolio SET shares = {int(sharesPurchased + shares)} WHERE userId = {session['user_id']} AND symbol = '{symbolPurchased}'")
                    connection.commit()

                cursor.execute(f"UPDATE users SET cash = {cash - price} WHERE id = {session['user_id']}")
                connection.commit()

                now = datetime.now()
                dateTime = now.strftime("%Y-%m-%d %H:%M:%S")
                cursor.execute(f"INSERT INTO history (userId, symbol, shares, price, date) VALUES ({session['user_id']}, '{symbol}', {shares}, {price}, '{dateTime}')")
                connection.commit()
                connection.close()

                return redirect("/")

        else:
            return apology("Invalid shares value. Please, try again")

    else:
        return render_template("buy.html")


@app.route("/history")
@login_required
def history():
    connection = pool.get_connection()
    cursor = connection.cursor()

    """Show history of transactions"""
    histories = cursor.execute(f"SELECT symbol, shares, price, date FROM history WHERE userId = {session['user_id']} ORDER BY id DESC")
    histories = cursor.fetchall()
    connection.close()
    return render_template("history.html", histories=histories)


@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in"""

    # Forget any user_id
    session.clear()

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        # Ensure username was submitted
        if not request.form.get("username"):
            return apology("must provide username", 403)

        # Ensure password was submitted
        elif not request.form.get("password"):
            return apology("must provide password", 403)

        # Query database for username
        connection = pool.get_connection()
        cursor = connection.cursor()

        user = cursor.execute(f"SELECT * FROM users WHERE username = '{request.form.get('username')}'")
        user = cursor.fetchall()
        connection.close()

        # Ensure username exists and password is correct
        if len(user) != 1 or not check_password_hash(user[0][2], request.form.get("password")):
            return apology("invalid username and/or password", 403)

        # Remember which user has logged in
        session["user_id"] = user[0][0]

        # Redirect user to home page
        return redirect("/")

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("login.html")


@app.route("/logout")
def logout():
    """Log user out"""

    # Forget any user_id
    session.clear()

    # Redirect user to login form
    return redirect("/")


@app.route("/quote", methods=["GET", "POST"])
@login_required
def quote():
    """Get stock quote."""
    if request.method == "GET":
        return render_template("quote.html")

    else:
        symbol = request.form.get("symbol")

        if not symbol:
            return apology("Invalid symbol. Please, try again")

        stockData = lookup(symbol)
        if stockData is None:
            return apology("The symbol entered is invalid, or the connection with the database was lost. Please, try again")

        stockName = stockData['name']
        stockSymbol = stockData['symbol']
        stockPrice = stockData['price']

        return render_template("quoted.html", name=stockName, symbol=stockSymbol, price=stockPrice)


@app.route("/register", methods=["GET", "POST"])
def register():
    """Register user"""
    if request.method == "POST":
        # Form validator
        username = request.form.get("username")
        password = request.form.get("password")
        confirmation = request.form.get("confirmation")

        connection = pool.get_connection()
        cursor = connection.cursor()

        alreadyExists = cursor.execute(f"SELECT username FROM users WHERE username = '{username}'")
        alreadyExists = cursor.fetchone()

        if username == "" or password == "" or confirmation == "" or password != confirmation:
            connection.close()
            return apology("Invalid credentials. Please, try again")
        if alreadyExists:
            connection.close()
            return apology("The username already exists. Please, try again")
        else:
            hashedPassword = generate_password_hash(password, method="pbkdf2:sha256", salt_length=8)
            cursor.execute(f"INSERT INTO users (username, hash, cash) VALUES ('{username}', '{hashedPassword}', 10000)")
            connection.commit()
            connection.close()
            return redirect("/")

    else:
        return render_template("register.html")


@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    connection = pool.get_connection()
    cursor = connection.cursor()

    """Sell shares of stock"""
    if request.method == "POST":
        symbol = request.form.get('symbol')
        shares = request.form.get('shares')

        if not shares.isdigit():
            return apology("Invalid shares. Please, enter a valid value")
        else:
            shares = int(shares)

        quote = lookup(symbol)
        price = round(quote['price'] * shares, 2)

        cash = cursor.execute(f"SELECT cash FROM users WHERE id = {session['user_id']}")
        cash = cursor.fetchone()
        cash = float(cash[0])

        alreadyExists = cursor.execute(
            f"SELECT id, symbol, shares FROM portfolio WHERE (symbol = '{symbol}' AND userId = {session['user_id']})")
        alreadyExists = cursor.fetchall()

        sharesSold = alreadyExists[0][2]
        stockId = alreadyExists[0][0]
        if len(alreadyExists) == 0:
            connection.close()
            return apology("The symbol entered is invalid, or the connection with the database was lost. Please, try again")
        elif shares > sharesSold:
            connection.close()
            return apology("Invalid shares. Shares entered are greater than what you own. Please, try again")
        elif shares < 1:
            connection.close()
            return apology("Invalid value. Please, try again")
        else:
            if shares == sharesSold:
                cursor.execute(f"DELETE FROM portfolio WHERE id = {stockId}")
                connection.commit()
            else:
                cursor.execute(f"UPDATE portfolio SET shares = {sharesSold - shares} WHERE id = {stockId}")
                connection.commit()

            cursor.execute(f"UPDATE users SET cash = {cash + price} WHERE id = {session['user_id']}")
            connection.commit()

            now = datetime.now()
            dateTime = now.strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute(f"INSERT INTO history (userId, symbol, shares, price, date) VALUES ({session['user_id']}, '{symbol}', {int(-shares)}, {price}, '{dateTime}')")
            connection.commit()
            connection.close()

            return redirect("/")
    else:
        symbols = cursor.execute(f"SELECT symbol FROM portfolio WHERE userId = {session['user_id']}")
        symbols = cursor.fetchall()
        connection.close()
        return render_template("sell.html", symbols=symbols)


def errorhandler(e):
    """Handle error"""
    if not isinstance(e, HTTPException):
        e = InternalServerError()
    return apology(e.name, e.code)


# Listen for errors
for code in default_exceptions:
    app.errorhandler(code)(errorhandler)