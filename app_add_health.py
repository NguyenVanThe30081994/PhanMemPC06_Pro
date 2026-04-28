# Add health check blueprint to app.py
with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Add import
if 'from routes.health import health_bp' not in content:
    import_line = 'from routes.reporting import reporting_bp'
    content = content.replace(
        import_line,
        import_line + '\nfrom routes.health import health_bp'
    )

# Add blueprint registration
if 'app.register_blueprint(health_bp)' not in content:
    register_line = 'app.register_blueprint(zalo_bp)'
    content = content.replace(
        register_line,
        register_line + '\napp.register_blueprint(health_bp)'
    )

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ Health check blueprint added to app.py")
