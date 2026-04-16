import math

ZONES = [
    {"name": "Connaught-Place-Delhi", "lat": 28.6315, "lon": 77.2167},
    {"name": "Bandra-Mumbai", "lat": 19.076, "lon": 72.8777},
    {"name": "OMR-Chennai", "lat": 13.0827, "lon": 80.2707},
    {"name": "Hitec-City-Hyderabad", "lat": 17.4435, "lon": 78.3772},
    {"name": "Koramangala-Bangalore", "lat": 12.9352, "lon": 77.6245},
]

def get_zone_from_gps(lat: float, lon: float) -> str:
    """
    Derive the correct zone directly from GPS coordinates 
    to prevent zone spoofing.
    """
    if lat is None or lon is None:
        return "Default-Zone"
    
    closest_zone = "Default-Zone"
    min_dist = float('inf')
    
    for z in ZONES:
        # Simple euclidean distance for rough mapping
        dist = math.sqrt((lat - z["lat"])**2 + (lon - z["lon"])**2)
        if dist < min_dist:
            min_dist = dist
            closest_zone = z["name"]
            
    # Apply a max radius threshold (roughly 2.0 degrees ~ 220km)
    if min_dist > 2.0:
        return "Default-Zone"
        
    return closest_zone
