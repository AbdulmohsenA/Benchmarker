I need you to create a full Express.js server in JavaScript with the following specifications:

1. **Server Setup**
   - Use Express.js framework.
   - Run the server on host `0.0.0.0` and port `5000`.
   - Ensure all dependencies (`express`, `sqlite3`, `jsonwebtoken`, `bcrypt` or similar) are installed and included in `package.json`. Don't set a version number, just list the names

2. **Routes**
   - **GET /**  
     - Respond with status 200 and plain text: `"Hello, World!"`.
   
   - **GET /health**  
     - Respond with status 200 and JSON: `{ "status": "healthy" }`.

   - **POST /register**  
     - Accept JSON payload: `{ "username": "<string>", "password": "<string>" }`.
     - Hash the password using bcrypt (or similar secure hashing).
     - Store the user credentials in an SQLite3 database (`users` table).
     - Return JSON with a success message and optionally a JWT token.

   - **POST /login**  
     - Accept JSON payload: `{ "username": "<string>", "password": "<string>" }`.
     - Validate credentials against the SQLite3 database.
     - If valid, return a JWT token in JSON.
     - If invalid, return status 401 with a JSON error message.

     Ensure that the server runs using npm start

     Run the server after implementation using exec to ensure it starts correctly.