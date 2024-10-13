from fastapi import FastAPI, Request, Response, Form,Path, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from google.cloud import firestore
from fastapi.responses import HTMLResponse
from google.auth.transport import requests
import google.oauth2.id_token, uuid
from google.auth.transport import requests
from fastapi import Request
from datetime import datetime
from fastapi import HTTPException


app = FastAPI()

# Firestore client
firestore_db = firestore.Client()

# Mount static files directory
app.mount("/static", StaticFiles(directory="static"), name="static")

# Jinja2 templates directory
templates = Jinja2Templates(directory="templates")

# Request adapter for Firebase
firebase_request_adapter = requests.Request()

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    id_token = request.cookies.get("token")
    error_message = "No Error Here"
    user_token = None
    user_email = None
    user_id = None

    if id_token:
        try:
            user_token = google.oauth2.id_token.verify_firebase_token(id_token, firebase_request_adapter)

            user_email = user_token.get('email')
            user_id = user_token.get('user_id')

            
            user_ref = firestore_db.collection('users').document(user_id)
            user_data = {
                'email': user_email,
                'user_id': user_id
            }
            user_ref.set(user_data, merge=True)  
        except ValueError as err:
            print(str(err))

    listOfrooms = get_rooms()
    user_bookings = []
    rooms = get_rooms()
    if user_id:
        bookings_ref = firestore_db.collection("bookings").where("user_id", "==", user_id).stream()
        user_bookings = [booking.to_dict() for booking in bookings_ref]

    return templates.TemplateResponse('main.html', {'request': request, 'user_token': user_token, 'error_message': error_message, 'user_bookings': user_bookings, "listOfrooms": listOfrooms,"rooms": rooms})


def validate_firebase_token(id_token):
    if not id_token:
        return None
    try:
        return google.oauth2.id_token.verify_firebase_token(id_token, firebase_request_adapter)
    except ValueError as err:
        print(str(err))
        return None
    
@app.get("/rooms", response_class=HTMLResponse)
async def list_rooms(request: Request):
    # Fetch the list of rooms from Firestore
    rooms = get_rooms()
    return templates.TemplateResponse("rooms.html", {"request": request, "rooms": rooms})


@app.post("/addRoom", response_class=HTMLResponse)
async def add_room(request: Request):
    id_token = request.cookies.get("token")
    user_token = validate_firebase_token(id_token)
    if not user_token:
        return Response(status_code=403, content="Unauthorized")

    try:
        room_data = await request.json()
        room_name = room_data.get("roomName")
        room_capacity = room_data.get("roomCapacity")
        room_price = room_data.get("roomPrice")

        if not room_name or not room_capacity:
            raise ValueError("Room name and capacity are required")
        
        existing_room = firestore_db.collection('rooms').where('room_name', '==', room_name).get()
        if existing_room:
            return HTMLResponse(content='<script>alert("Room already exists. Please try a different room number.");window.location.href="/add-room-page/";</script>')
        
          # Add the room to Firestore
        room_ref = firestore_db.collection("rooms").document()
        room_ref.set({"room_name": room_name, "room_capacity": room_capacity, "room_price": room_price})
        
        return HTMLResponse(content='<script>alert("Room added succesfully.");window.location.href="/add-room-page/";</script>')
    except Exception as e:
        print(f"Error adding room: {e}")
        return Response(status_code=500, content="Internal Server Error")
    
@app.get("/bookRoom", response_class=HTMLResponse)
async def book_room_form(request: Request):
    id_token = request.cookies.get("token")
    user_token = validate_firebase_token(id_token)
    listOfrooms = get_rooms()
    return templates.TemplateResponse("booking_form.html", {"request": request, "user_token": user_token, "listOfrooms": listOfrooms})

# Get rooms from Firestore
def get_rooms():
    rooms_ref = firestore_db.collection("rooms")
    rooms = []
    for room in rooms_ref.stream():
        rooms.append(room.to_dict())
    return rooms

def is_room_booked(room_name, booking_date):
    bookings_ref = firestore_db.collection("bookings").where("room_name", "==", room_name).where("date", "==", booking_date.strftime("%Y-%m-%d")).stream()
    return any(booking.exists for booking in bookings_ref)

@app.post("/bookRoom", response_class=Response)
async def book_room(request: Request):
    try:
        id_token = request.cookies.get("token")
        user_token = validate_firebase_token(id_token)
        if not user_token:
            return Response(status_code=403)

        form = await request.form()
        room_name = form.get("roomName")
        date = form.get("date")
        time = form.get("time")
        if not room_name or not date or not time:
            raise ValueError("Room name, date, and time are required")

        # Convert date string to datetime object
        booking_date = datetime.strptime(date, "%Y-%m-%d")

        # Check if the room is already booked on the given date
        if is_room_booked(room_name, booking_date):
            return HTMLResponse(content='<script>alert("Room already booked on the same date!"); window.location.href="/";</script>')

        # Generate a unique booking ID
        booking_id = str(uuid.uuid4())

        # Add booking data to Firestore
        booking_data = {
            "booking_id": booking_id,
            "room_name": room_name,
            "user_id": user_token["user_id"],  
            "date": date,
            "time": time,
        }
        firestore_db.collection("bookings").document(booking_id).set(booking_data)

        # Add booking data to the "days" collection
        day_doc_ref = firestore_db.collection("days").document(date)
        day_doc = day_doc_ref.get()
        if day_doc.exists:
            day_doc_ref.update({booking_id: booking_data})
        else:
            day_doc_ref.set({booking_id: booking_data})

        # Return success message
        return HTMLResponse(content='<script>alert("Room booked successfully!"); window.location.href="/";</script>')    
    except Exception as e:
        print(f"Error booking room: {e}")
        return Response(status_code=500, content=str(e))

    
# Function to get all bookings made by the current user
def get_user_bookings(user_id):
    user_bookings = []
    bookings_ref = firestore_db.collection("bookings").where("user_id", "==", user_id).stream()
    for booking in bookings_ref:
        user_bookings.append(booking.to_dict())
    return user_bookings

    
# Route to display all bookings made by the current user
@app.get("/", response_class=HTMLResponse)
async def main_page(request: Request):
    try:
        id_token = request.cookies.get("token")
        user_token = validate_firebase_token(id_token)
        if not user_token:
            return Response(status_code=403)
        
        # Fetch all bookings made by the current user
        user_bookings = get_user_bookings(user_token["user_id"])
        
        rooms = get_rooms()
        return templates.TemplateResponse("main_page.html", {"request": request, "user_token": user_token, "user_bookings": user_bookings,"rooms": rooms})
    except Exception as e:
        print(f"Error fetching user bookings: {e}")
        return Response(status_code=500, content=str(e))


@app.post("/userBookings", response_class=HTMLResponse)
async def user_bookings_by_room(request: Request, roomName: str = Form(...)):
    try:
        id_token = request.cookies.get("token")
        user_token = validate_firebase_token(id_token)
        if not user_token:
            return Response(status_code=403)
        
        # Fetch bookings made by the current user for the selected room
        user_bookings = get_user_bookings_by_room(user_token["user_id"], roomName)
        listOfrooms = get_rooms()
        return templates.TemplateResponse("main.html", {"request": request, "user_token": user_token, "user_bookings": user_bookings,"listOfrooms":listOfrooms})
    except Exception as e:
        print(f"Error fetching user bookings by room: {e}")
        return Response(status_code=500, content=str(e))

# Function to get all bookings made by the current user for a specific room
def get_user_bookings_by_room(user_id, room_name):
    user_bookings = []
    bookings_ref = firestore_db.collection("bookings").where("user_id", "==", user_id).where("room_name", "==", room_name).stream()
    for booking in bookings_ref:
        user_bookings.append(booking.to_dict())
    return user_bookings

# Function to delete a booking
@app.post("/deleteBooking")
async def delete_booking(request: Request, booking_id: str = Form(...)):
    try:
        id_token = request.cookies.get("token")
        user_token = validate_firebase_token(id_token)
        if not user_token:
            return Response(status_code=403)

        # Get the booking reference by ID
        booking_ref = firestore_db.collection("bookings").document(booking_id)
        booking = booking_ref.get()
        if booking.exists:
            booking_data = booking.to_dict()
            if booking_data["user_id"] == user_token["user_id"]:
                # Delete the booking
                booking_ref.delete()
                return HTMLResponse(content='<script>alert("Deleted successfully!"); window.location.href="/";</script>')
            else:
                return Response(status_code=403)
        else:
            return Response(status_code=404)
    except Exception as e:
        print(f"Error deleting booking: {e}")
        return Response(status_code=500)
    

# Route to handle the submission of the edited booking
@app.get("/editBooking/{booking_id}", response_class=HTMLResponse)
async def edit_booking_form(request: Request, booking_id: str = Path(...)):
    try:
        id_token = request.cookies.get("token")
        user_token = validate_firebase_token(id_token)
        if not user_token:
            return Response(status_code=403)

        # Fetch the booking data to prepopulate the form
        booking_ref = firestore_db.collection("bookings").document(booking_id)
        booking = booking_ref.get()
        if booking.exists:
            booking_data = booking.to_dict()
            if booking_data["user_id"] == user_token["user_id"]:
                return templates.TemplateResponse("edit_booking.html", {"request": request, "user_token": user_token, "booking_data": booking_data})
            else:
                return Response(status_code=403)
        else:
            return Response(status_code=404)
    except Exception as e:
        print(f"Error fetching booking for editing: {e}")
        return Response(status_code=500, content=str(e))

# Route to handle the submission of the edited booking
@app.post("/editBooking/{booking_id}", response_class=HTMLResponse)
async def edit_booking(request: Request, booking_id: str = Path(...)):
    try:
        id_token = request.cookies.get("token")
        user_token = validate_firebase_token(id_token)
        if not user_token:
            return Response(status_code=403)

        form = await request.form()
        new_date = form.get("date")
        new_time = form.get("time")
        
        # Fetch the booking data to ensure the user owns the booking
        booking_ref = firestore_db.collection("bookings").document(booking_id)
        booking = booking_ref.get()
        if booking.exists:
            booking_data = booking.to_dict()
            if booking_data["user_id"] == user_token["user_id"]:
                # Update the booking data
                booking_ref.update({"date": new_date, "time": new_time})
                return HTMLResponse(content='<script>alert("Booking updated successfully!"); window.location.href="/";</script>') 
            else:
                return Response(status_code=403)
        else:
            return Response(status_code=404)
    except Exception as e:
        print(f"Error editing booking: {e}")
        return Response(status_code=500, content=str(e))
    
@app.post("/filterBookingsByDate", response_class=HTMLResponse)
async def filter_bookings_by_date(request: Request):
    try:
        id_token = request.cookies.get("token")
        user_token = validate_firebase_token(id_token)
        if not user_token:
            return Response(status_code=403)

        form = await request.form()
        filter_date_str = form.get("filterDate")
        if not filter_date_str:
            raise ValueError("Please select a valid date")

        # Convert filter date string to datetime object
        filter_date = datetime.strptime(filter_date_str, "%Y-%m-%d")

        # Get all room bookings for the selected date
        room_bookings = get_room_bookings_by_date(filter_date)

        return templates.TemplateResponse("filtered_bookings.html", {"request": request, "user_token": user_token, "filter_date": filter_date, "room_bookings": room_bookings})
    except Exception as e:
        print(f"Error filtering bookings by date: {e}")
        return Response(status_code=500, content=str(e))

# Function to get room bookings for a specific date
def get_room_bookings_by_date(filter_date):
    room_bookings = {}
    rooms_ref = firestore_db.collection("rooms").stream()
    for room in rooms_ref:
        room_data = room.to_dict()
        room_name = room_data["room_name"]
        # Get bookings for the room on the specified date
        bookings_ref = firestore_db.collection("bookings").where("room_name", "==", room_name).where("date", "==", filter_date.strftime("%Y-%m-%d")).stream()
        bookings = [booking.to_dict() for booking in bookings_ref]
        # Only add rooms with bookings on the specified date
        if bookings:
            room_bookings[room_name] = bookings
    return room_bookings

@app.get("/roomBookings/{room_name}", response_class=HTMLResponse)
async def room_bookings(request: Request, room_name: str):
    try:
        id_token = request.cookies.get("token")
        user_token = validate_firebase_token(id_token)
        if not user_token:
            return Response(status_code=403)

        # Fetch bookings made for the selected room
        room_bookings = get_room_bookings_by_room(room_name)
        return templates.TemplateResponse("room_bookings.html", {"request": request, "user_token": user_token, "room_name": room_name, "room_bookings": room_bookings})
    except Exception as e:
        print(f"Error fetching room bookings: {e}")
        return Response(status_code=500, content=str(e))
    
def get_room_bookings_by_room(room_name):
    room_bookings = []
    bookings_ref = firestore_db.collection("bookings").where("room_name", "==", room_name).stream()
    for booking in bookings_ref:
        room_bookings.append(booking.to_dict())
    return room_bookings

async def get_user_id(request: Request):
    user_id = request.cookies.get("user_id")
    if not user_id:
        # If user ID is not found, you might raise an HTTPException or return None, depending on your requirements
        raise HTTPException(status_code=401, detail="User not authenticated")
    return user_id

# Define the delete_room endpoint
@app.post("/delete-room/{room_name}")
async def delete_room(room_name: str, user_id: str = Depends(get_user_id)):
    room_ref = firestore_db.collection("rooms").document(room_name)
    room_data = room_ref.get()
    
    if not room_data.exists:
        raise HTTPException(status_code=404, detail="Room not found")
    
    room_user_id = room_data.to_dict().get("user_id")
    if room_user_id != user_id:
        return HTMLResponse(content='<script>alert("You are not authorized to remove this room!"); window.location.href="/";</script>')

    bookings = firestore_db.collection("bookings").where("room_id", "==", room_name).stream()
    if any(bookings):
        return HTMLResponse(content='<script>alert("Cannot delete because bookings are associated with this room!"); window.location.href="/";</script>')
    
    room_ref.delete()
    return HTMLResponse(content='<script>alert("Room deleted successfully"); window.location.href="/";</script>')

