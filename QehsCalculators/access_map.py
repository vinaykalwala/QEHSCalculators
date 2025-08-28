CALCULATORS = [
    # Quality Calculators
    # {"name": "Product Quality Score", "url_name": "quality_score", "plan_type": "individual", "category": "quality"},
    # {"name": "Defect Density Calculator", "url_name": "defect_density", "plan_type": "employee", "category": "quality"},
    # {"name": "Six Sigma Calculator", "url_name": "six_sigma", "plan_type": "corporate", "category": "quality"},
    
    # Environment Calculators
    {"name": "CO2 Emission Calculator", "url_name": "co2_calculator", "plan_type": "employee", "category": "environment"},
    # {"name": "Carbon Footprint Calculator", "url_name": "carbon_footprint", "plan_type": "employee", "category": "environment"},
    # {"name": "Water Usage Calculator", "url_name": "water_usage", "plan_type": "corporate", "category": "environment"},
    
    # Health Calculators
    # {"name": "BMI Calculator", "url_name": "bmi_calculator", "plan_type": "individual", "category": "health"},
    # {"name": "Calorie Calculator", "url_name": "calorie_calculator", "plan_type": "employee", "category": "health"},
    # {"name": "Health Risk Assessment", "url_name": "health_risk", "plan_type": "corporate", "category": "health"},
    
    # Safety Calculators
    # {"name": "Risk Assessment Calculator", "url_name": "risk_assessment", "plan_type": "employee", "category": "safety"},
    # {"name": "Incident Rate Calculator", "url_name": "incident_rate", "plan_type": "corporate", "category": "safety"},
    # {"name": "Safety Compliance Check", "url_name": "safety_compliance", "plan_type": "corporate", "category": "safety"},
    
    # Fire Calculators
    # {"name": "Fire Risk Assessment", "url_name": "fire_risk", "plan_type": "individual", "category": "fire"},
    # {"name": "Evacuation Time Calculator", "url_name": "evacuation_time", "plan_type": "employee", "category": "fire"},
    # {"name": "Fire Safety Compliance", "url_name": "fire_safety", "plan_type": "corporate", "category": "fire"},
    
    
]

# Define category information
CATEGORIES = {
    "quality": {
        "name": "Quality",
        "icon": "fa-check-circle",
        "description": "Quality management and assurance calculators"
    },
    "environment": {
        "name": "Environment",
        "icon": "fa-leaf",
        "description": "Environmental impact and sustainability calculators"
    },
    "health": {
        "name": "Health",
        "icon": "fa-heartbeat",
        "description": "Health and wellness calculators"
    },
    "safety": {
        "name": "Safety",
        "icon": "fa-shield-alt",
        "description": "Workplace safety calculators"
    },
    "fire": {
        "name": "Fire Safety",
        "icon": "fa-fire-extinguisher",
        "description": "Fire safety and prevention calculators"
    },
    
}

# Plan hierarchy
PLAN_HIERARCHY = {
    "individual": 1,
    "employee": 2,
    "corporate": 3
}