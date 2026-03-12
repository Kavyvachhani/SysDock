# InfraVision Agent — Deploy to PyPI

## 1. Install build tools
```bash
pip install build twine
```

## 2. Build distributions
```bash
cd infravision-agent
python -m build
# Creates: dist/infravision_agent-1.0.0.tar.gz
#          dist/infravision_agent-1.0.0-py3-none-any.whl
```

## 3. Verify the build
```bash
twine check dist/*
```

## 4. Upload to PyPI
```bash
# First time: create account at https://pypi.org/account/register/
# Create API token at https://pypi.org/manage/account/token/
twine upload dist/*
# Username: __token__
# Password: pypi-xxxxxxxx (your API token)
```

## 5. Install from PyPI (after publish)
```bash
pip install infravision-agent
pip install "infravision-agent[docker]"   # includes docker-py
```

## 6. Deploy on any EC2 / Linux server
```bash
# Install
pip install infravision-agent
sudo infravision install --port 5010

# Test
curl http://localhost:5010/health
curl http://localhost:5010/

# Live terminal dashboard
infravision dash

# One-shot status
infravision status

# Check all dependencies
infravision check
```

## 7. AWS Security Group (required)
```bash
aws ec2 authorize-security-group-ingress \
  --group-id sg-xxxxxxxxxx \
  --protocol tcp \
  --port 5010 \
  --cidr <your-monitoring-server-ip>/32
```

## Quick test without installing
```bash
cd infravision-agent
PYTHONPATH=. python3 -m infravision_agent start --port 5010
```
