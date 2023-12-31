import boto3, requests, time, subprocess

def get_metadata_token():
    try:
        response = requests.put('http://169.254.169.254/latest/api/token', headers={'X-aws-ec2-metadata-token-ttl-seconds': '60'}, timeout=2)
        response.raise_for_status()
        token = response.text
        # print(f"Metadata Token: {token}")
        return token
    except requests.exceptions.RequestException as e:
        print(f"Error: Unable to fetch metadata token - {e}")
        return None

def get_instance_id():
    TOKEN = get_metadata_token()
    
    if not TOKEN:
        print("Error: Unable to obtain metadata token. Exiting.")
        return None

    try:
        response = requests.get('http://169.254.169.254/latest/meta-data/instance-id', headers={'X-aws-ec2-metadata-token': TOKEN}, timeout=2)
        response.raise_for_status()  # Check for errors in the response
        instance_id = response.text
        # print(f"Instance ID: {instance_id}")
        return instance_id
    except requests.exceptions.RequestException as e:
        print(f"Error: Unable to fetch instance ID - {e}")
        return None

def wait_for_volume_completion(ec2_client, volume_id):
    while True:
        volume_status = ec2_client.describe_volumes_modifications(VolumeIds=[volume_id])
        modification_state = volume_status['VolumesModifications'][0]['ModificationState']

        if modification_state == 'completed':
            break

        time.sleep(10)

def resize_volume(ec2_client, volume_id, new_size_gb):
    ec2_client.modify_volume(VolumeId=volume_id, Size=new_size_gb)

def get_local_device_name(aws_device_name):
    if aws_device_name.startswith('/dev/sd'):
        return '/dev/xvd' + aws_device_name[7:]
    elif aws_device_name.startswith('/dev/nvme'):
        return '/dev/nvme' + aws_device_name[9:]
    else:
        return aws_device_name

def main():
    # Setting adjustable parameters
    MULTIPLIER = 1.1
    THRESHOLD = 80
    AWS_REGION = "us-east-1"

    # Get the instance ID dynamically
    instance_id = get_instance_id()
    print(f"Instance ID: {instance_id}")

    if not instance_id:
        print("Error: Unable to determine instance ID. Exiting.")
        return

    # GET volumes
    ec2 = boto3.resource('ec2', region_name=AWS_REGION)
    instance = ec2.Instance(instance_id)
    volumes = list(instance.volumes.all())
    print(f"Volumes attached to instance: {[volume.id for volume in volumes]}")

    if not volumes:
        print("No volumes attached to the instance.")
        return

    # Loop through all volumes
    for volume in volumes:
        volume_id = volume.id

        # AWS CLI command for getting the current volume size
        ec2_client = boto3.client('ec2', region_name=AWS_REGION)
        current_size = ec2_client.describe_volumes(VolumeIds=[volume_id])['Volumes'][0]['Size']
        print(f"Current volume size for volume {volume_id}: {current_size} GB")

        # Get local disk name based on disk name
        aws_device_name = volume.attachments[0]["Device"]
        local_device_name = get_local_device_name(aws_device_name)
        print(f"Local device name for volume {volume_id}: {local_device_name}")

        # Check Disk Usage for the current volume
        current_usage_output = subprocess.check_output(['df', '-h', local_device_name, '--output=pcent']).decode('utf-8').strip()
        # Extracting the actual value from the object
        current_usage_percentage = current_usage_output.split('\n')[1].strip()
        # Remove the percentage sign and convert to int
        current_usage = int(current_usage_percentage.rstrip('%'))
        # Remove the percent and convert to int
        print(f"Current disk usage for volume {volume_id}: {current_usage}%")

        # Condition to expand disk
        if current_usage > THRESHOLD:
            print(f"Disk usage for volume {volume_id} is above {THRESHOLD}%, expanding disk...")

            # Calculate the new size
            new_size = int(current_size * MULTIPLIER)

            # AWS CLI command for resizing the EBS volume
            resize_volume(ec2_client, volume_id, new_size)

            # Wait for volume modification to complete
            wait_for_volume_completion(ec2_client, volume_id)

            print(f"Disk expansion for volume {volume_id} complete.")
        else:
            print(f"Disk usage for volume {volume_id} is below {THRESHOLD}%, no need to expand the disk.")

    print("All disk expansions complete.")

if __name__ == "__main__":
    main()
