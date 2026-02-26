# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Create a directory for the SQLite database to ensure persistence
RUN mkdir -p /app/instance

# Expose the port the app runs on
EXPOSE 8080

# Run the application
CMD ["python", "app.py"]
