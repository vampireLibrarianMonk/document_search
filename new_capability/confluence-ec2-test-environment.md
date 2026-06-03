# Confluence EC2 Test Environment

Stand up a self-hosted Confluence Data Center instance on EC2 to test the app's Confluence sync connector against a real Confluence API.

## Goal

Upload HOA documents as Confluence page attachments, then use `POST /sources/confluence/sync` to pull them into the document search app — validating the full pipeline end-to-end.

## Prerequisites

- AWS credentials configured locally (`~/.aws/credentials` or environment variables)
- A key pair in the target region (or we create one)
- HOA documents ready to upload (already in `data/uploads/`)

## Plan

### Phase 1: Launch EC2 Instance

1. **Create a security group** allowing inbound:
   - TCP 22 (SSH) from your IP
   - TCP 8090 (Confluence HTTP) from your IP
   - TCP 8091 (Confluence collaborative editing) from your IP
2. **Create a key pair** (if needed) and save the `.pem` file locally
3. **Launch instance**:
   - AMI: Amazon Linux 2023 (latest x86_64)
   - Instance type: `t3.large` (2 vCPU, 8 GB RAM — Confluence minimum)
   - Root volume: 30 GB gp3
   - Security group from step 1
   - Key pair from step 2
4. **Tag**: `Name=confluence-test`

### Phase 2: Install Docker & Run Confluence

SSH into the instance, then:

```bash
# Install Docker
sudo dnf update -y
sudo dnf install -y docker
sudo systemctl enable --now docker
sudo usermod -aG docker ec2-user

# Install Docker Compose plugin
sudo mkdir -p /usr/local/lib/docker/cli-plugins
sudo curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64 \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

# Log out and back in for group membership
exit
```

Re-SSH, then create `~/confluence/docker-compose.yml`:

```yaml
services:
  confluence:
    image: atlassian/confluence:8.5-ubuntu-jdk17
    ports:
      - "8090:8090"
      - "8091:8091"
    environment:
      - ATL_TOMCAT_CONTEXTPATH=/
      - JVM_MINIMUM_MEMORY=1024m
      - JVM_MAXIMUM_MEMORY=4096m
    volumes:
      - confluence-data:/var/atlassian/application-data/confluence
    restart: unless-stopped

  postgres:
    image: postgres:15
    environment:
      - POSTGRES_DB=confluence
      - POSTGRES_USER=confluence
      - POSTGRES_PASSWORD=confluence123
    volumes:
      - pg-data:/var/lib/postgresql/data
    restart: unless-stopped

volumes:
  confluence-data:
  pg-data:
```

```bash
cd ~/confluence
docker compose up -d
```

### Phase 3: Configure Confluence

1. Open `http://<EC2_PUBLIC_IP>:8090` in browser
2. Select **Trial installation** (free 3-hour evaluation, no license key needed — or use a [free Data Center trial license](https://my.atlassian.com/license/evaluation))
3. Choose **PostgreSQL** as the database:
   - Host: `postgres`
   - Port: `5432`
   - Database: `confluence`
   - User: `confluence`
   - Password: `confluence123`
4. Complete the setup wizard (create admin user)
5. Create a space called `HOA` (space key: `HOA`)

### Phase 4: Upload HOA Documents

1. In the `HOA` space, create pages for each document category:
   - "Closing Documents"
   - "HOA Governance"
   - "Insurance"
   - "Inspection Reports"
2. Attach the PDF/DOCX files from `data/uploads/` to the appropriate pages
3. Generate an API token:
   - Go to user profile → Settings → Personal Access Tokens
   - Create a token with read access

### Phase 5: Configure & Test the App

1. Update the app's configuration (via Settings UI or `local.env`):
   ```
   CONFLUENCE_URL=http://<EC2_PUBLIC_IP>:8090
   CONFLUENCE_EMAIL=admin
   CONFLUENCE_API_TOKEN=<personal-access-token>
   ```

   Note: Confluence Data Center uses Personal Access Tokens (PAT) with Bearer auth, not basic auth. The app's connector should use the token as a Bearer token header. If the current connector uses basic auth (email + API token like Confluence Cloud), you may need to adjust the auth method or use basic auth with the admin username and password instead.

2. Trigger a sync:
   ```bash
   curl -X POST http://localhost:8000/sources/confluence/sync \
     -H 'Content-Type: application/json' \
     -d '{"space_keys": ["HOA"]}'
   ```

3. Verify:
   - Documents appear in the app's document list
   - Search returns results from synced content
   - Ask AI can answer questions using the synced documents

### Phase 6: Teardown

When done testing:

```bash
# Terminate the instance
aws ec2 terminate-instances --instance-ids <INSTANCE_ID>

# Clean up security group (after instance terminates)
aws ec2 delete-security-group --group-id <SG_ID>

# Delete key pair if created for this
aws ec2 delete-key-pair --key-name confluence-test-key
```

## Estimated Cost

- `t3.large` on-demand: ~$0.0832/hr (~$2/day)
- 30 GB gp3 EBS: ~$2.40/month
- Total for a day of testing: **~$2.50**

## Automation Script (Optional)

A launch script can be added to `scripts/` to automate Phase 1-2:

```bash
#!/bin/bash
set -euo pipefail

REGION=${AWS_REGION:-us-east-1}
KEY_NAME="confluence-test-key"
SG_NAME="confluence-test-sg"
INSTANCE_TYPE="t3.large"
AMI_ID=$(aws ec2 describe-images --region $REGION \
  --owners amazon \
  --filters "Name=name,Values=al2023-ami-2023*-x86_64" "Name=state,Values=available" \
  --query 'Images | sort_by(@, &CreationDate) | [-1].ImageId' --output text)

MY_IP=$(curl -s https://checkip.amazonaws.com)/32

# Create key pair
aws ec2 create-key-pair --region $REGION --key-name $KEY_NAME \
  --query 'KeyMaterial' --output text > ~/.ssh/${KEY_NAME}.pem
chmod 600 ~/.ssh/${KEY_NAME}.pem

# Create security group
VPC_ID=$(aws ec2 describe-vpcs --region $REGION --filters "Name=isDefault,Values=true" \
  --query 'Vpcs[0].VpcId' --output text)
SG_ID=$(aws ec2 create-security-group --region $REGION --group-name $SG_NAME \
  --description "Confluence test" --vpc-id $VPC_ID --query 'GroupId' --output text)
aws ec2 authorize-security-group-ingress --region $REGION --group-id $SG_ID \
  --protocol tcp --port 22 --cidr $MY_IP
aws ec2 authorize-security-group-ingress --region $REGION --group-id $SG_ID \
  --protocol tcp --port 8090 --cidr $MY_IP
aws ec2 authorize-security-group-ingress --region $REGION --group-id $SG_ID \
  --protocol tcp --port 8091 --cidr $MY_IP

# Launch instance with user-data to install Docker
INSTANCE_ID=$(aws ec2 run-instances --region $REGION \
  --image-id $AMI_ID --instance-type $INSTANCE_TYPE \
  --key-name $KEY_NAME --security-group-ids $SG_ID \
  --block-device-mappings '[{"DeviceName":"/dev/xvda","Ebs":{"VolumeSize":30,"VolumeType":"gp3"}}]' \
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=confluence-test}]" \
  --user-data '#!/bin/bash
dnf update -y
dnf install -y docker
systemctl enable --now docker
usermod -aG docker ec2-user
mkdir -p /usr/local/lib/docker/cli-plugins
curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64 -o /usr/local/lib/docker/cli-plugins/docker-compose
chmod +x /usr/local/lib/docker/cli-plugins/docker-compose' \
  --query 'Instances[0].InstanceId' --output text)

echo "Instance: $INSTANCE_ID"
echo "Waiting for public IP..."
aws ec2 wait instance-running --region $REGION --instance-ids $INSTANCE_ID
PUBLIC_IP=$(aws ec2 describe-instances --region $REGION --instance-ids $INSTANCE_ID \
  --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)

echo "SSH: ssh -i ~/.ssh/${KEY_NAME}.pem ec2-user@${PUBLIC_IP}"
echo "Confluence will be at: http://${PUBLIC_IP}:8090 (after setup)"
```

## Notes

- Confluence Data Center requires a trial license (free for 30 days from Atlassian)
- The Confluence container takes 2-3 minutes to start up on first boot
- If testing the Cloud connector specifically, use Confluence Cloud free tier instead (see README)
- The app's existing connector at `POST /sources/confluence/sync` expects Cloud-style auth (email + API token). For Data Center, Personal Access Tokens use Bearer auth — verify the connector handles both or use basic auth with username/password
