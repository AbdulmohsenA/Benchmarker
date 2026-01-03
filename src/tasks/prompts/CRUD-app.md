I need you to create a full Flask server in Python with the following specifications:

1. **Server Setup**
   - Use Flask framework.
   - Run the server on host `0.0.0.0` and port `5000`.
   - Ensure all dependencies are installed. Don't set a version number, just set the names
   - Use sqlite3 for a database

2. **Idea**
    - The server should be a CRUD application for notes where a user can add, delete, update, and read notes.

3. **Routes**
    - **GET /health**  
        - Respond with status 200 and JSON: `{ "status": "healthy" }`.

    - **GET /note**
        - given a node id in query, it should return the note text from the database in JSON with all fields (id, note, date_created, date_modified)
        - Returns 200 if found, if not 404

    - **POST /note**  
        - Accept JSON payload: `{ "note": "<string>" }`.
        - Adds the data in the database with the following data: id (UUID), note (text), date_created (datetime), date_modified (datetime)
        - Returns 201 if successful

    - **DELETE /note**  
        - given a node id in query, it should return the note text from the database in JSON with all fields (id, note, date_created, date_modified)
     
    - **PUT /note**
        - Updates a note with new text, accepts JSON payload: `{ "id": "<UUID>", "new_note": "<string>" }`

     Run the server after implementation using exec to ensure it starts correctly.