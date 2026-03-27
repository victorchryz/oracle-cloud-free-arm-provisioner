import itertools
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Union

import oci
import requests
from dotenv import load_dotenv

env_file = os.getenv("OCI_ENV_FILE", "/app/oci.env")
load_dotenv(env_file)

print(f"Loading env from: {env_file}")
print(f"File exists: {os.path.exists(env_file)}")
print(f"OCI_CONFIG value: {os.getenv('OCI_CONFIG', 'NOT SET')}")

ARM_SHAPE = "VM.Standard.A1.Flex"
E2_MICRO_SHAPE = "VM.Standard.E2.1.Micro"

OCI_CONFIG = os.getenv("OCI_CONFIG", "").strip()
OCT_FREE_AD = os.getenv("OCT_FREE_AD", "").strip()
DISPLAY_NAME = os.getenv("DISPLAY_NAME", "").strip()
WAIT_TIME = int(os.getenv("REQUEST_WAIT_TIME_SECS", "60").strip())
AD_WAIT_TIME = int(os.getenv("AD_WAIT_TIME_SECS", "20").strip())
RATE_LIMIT_WAIT_TIME = int(os.getenv("RATE_LIMIT_WAIT_TIME_SECS", "120").strip())
SSH_PUBLIC_KEY_FILE = os.getenv("SSH_PUBLIC_KEY_FILE", "").strip()
OCI_IMAGE_ID = os.getenv("OCI_IMAGE_ID", None).strip() if os.getenv("OCI_IMAGE_ID") else None
OCI_COMPUTE_SHAPE = os.getenv("OCI_COMPUTE_SHAPE", ARM_SHAPE).strip()
SECOND_MICRO_INSTANCE = os.getenv("SECOND_MICRO_INSTANCE", "False").strip().lower() == "true"
OCI_SUBNET_ID = os.getenv("OCI_SUBNET_ID", None).strip() if os.getenv("OCI_SUBNET_ID") else None
OPERATING_SYSTEM = os.getenv("OPERATING_SYSTEM", "").strip()
OS_VERSION = os.getenv("OS_VERSION", "").strip()
ASSIGN_PUBLIC_IP = os.getenv("ASSIGN_PUBLIC_IP", "false").strip()
BOOT_VOLUME_SIZE = os.getenv("BOOT_VOLUME_SIZE", "50").strip()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

iam_client = None
network_client = None
compute_client = None
OCI_USER_ID = None

IMAGE_LIST_KEYS = [
    "lifecycle_state",
    "display_name",
    "id",
    "operating_system",
    "operating_system_version",
    "size_in_mbs",
    "time_created",
]


def send_telegram_message(message: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"Failed to send Telegram message: {e}")


def init_oci_clients():
    global iam_client, network_client, compute_client, OCI_USER_ID
    config = oci.config.from_file(OCI_CONFIG)
    iam_client = oci.identity.IdentityClient(config)
    network_client = oci.core.VirtualNetworkClient(config)
    compute_client = oci.core.ComputeClient(config)
    OCI_USER_ID = config.get("user")


def write_into_file(file_path: str, data: str) -> None:
    with open(file_path, mode="a", encoding="utf-8") as file_writer:
        file_writer.write(data)


def list_all_instances(compartment_id: str):
    list_instances_response = compute_client.list_instances(compartment_id=compartment_id)
    return list_instances_response.data


def check_instance_state_and_write(
    compartment_id: str, shape: str, states=("RUNNING", "PROVISIONING"), tries: int = 3
) -> bool:
    for _ in range(tries):
        instance_list = list_all_instances(compartment_id=compartment_id)
        if shape == ARM_SHAPE:
            running_arm_instance = next(
                (
                    instance
                    for instance in instance_list
                    if instance.shape == shape and instance.lifecycle_state in states
                ),
                None,
            )
            if running_arm_instance:
                create_instance_details_file_and_notify(running_arm_instance, shape)
                print("Instance already exists. Exiting...")
                sys.exit(0)
        else:
            micro_instance_list = [
                instance
                for instance in instance_list
                if instance.shape == shape and instance.lifecycle_state in states
            ]
            if len(micro_instance_list) > 1 and SECOND_MICRO_INSTANCE:
                create_instance_details_file_and_notify(micro_instance_list[-1], shape)
                print("Instance already exists. Exiting...")
                sys.exit(0)
            if len(micro_instance_list) == 1 and not SECOND_MICRO_INSTANCE:
                create_instance_details_file_and_notify(micro_instance_list[-1], shape)
                print("Instance already exists. Exiting...")
                sys.exit(0)
        if tries - 1 > 0:
            time.sleep(60)
    return False


def execute_oci_command(client, method: str, *args, **kwargs):
    while True:
        try:
            response = getattr(client, method)(*args, **kwargs)
            data = response.data if hasattr(response, "data") else response
            return data
        except oci.exceptions.ServiceError as srv_err:
            data = {
                "status": srv_err.status,
                "code": srv_err.code,
                "message": srv_err.message,
            }
            send_telegram_message(
                f"❗️ Error executing OCI command: <code>{method}</code>\n"
                f"Status: {data['status']}\n"
                f"Code: {data['code']}\n"
                f"Message: {data['message']}"
            )
            if data["code"] in (
                "TooManyRequests",
                "Out of host capacity.",
                "InternalError",
            ) or data["message"] in ("Out of host capacity.", "Bad Gateway"):
                time.sleep(WAIT_TIME)
                continue
            raise


def read_ssh_public_key(public_key_file: Union[str, Path]) -> str:
    public_key_path = Path(public_key_file)
    if not public_key_path.is_file():
        raise FileNotFoundError(f"SSH public key file not found: {public_key_path}")
    with open(public_key_path, "r", encoding="utf-8") as pub_key_file:
        return pub_key_file.read()


def create_instance_details_file_and_notify(instance, shape: str) -> None:
    instance_details = {
        "display_name": instance.display_name,
        "shape": instance.shape,
        "id": instance.id,
        "lifecycle_state": instance.lifecycle_state,
        "time_created": str(instance.time_created),
    }
    file_name = f"instance_details_{shape.replace('.', '_')}.json"
    with open(file_name, "w") as f:
        json.dump(instance_details, f, indent=4)
    send_telegram_message(
        f"✅ <b>Instance Created!</b>\n\n"
        f"<b>Shape:</b> <code>{shape}</code>\n"
        f"<b>Name:</b> <code>{instance.display_name}</code>\n"
        f"<b>ID:</b> <code>{instance.id}</code>\n"
        f"<b>State:</b> <code>{instance.lifecycle_state}</code>\n\n"
        f"Details saved to <code>{file_name}</code>"
    )
    with open("/app/.success", "w") as f:
        f.write("done")


def launch_instance():
    user_info = iam_client.get_user(OCI_USER_ID).data
    oci_tenancy = user_info.compartment_id

    availability_domains = execute_oci_command(
        iam_client, "list_availability_domains", compartment_id=oci_tenancy
    )
    oci_ad_name = [
        item.name
        for item in availability_domains
        if any(item.name.endswith(oct_ad) for oct_ad in OCT_FREE_AD.split(","))
    ]

    oci_subnet_id = OCI_SUBNET_ID
    if not oci_subnet_id:
        subnets = execute_oci_command(network_client, "list_subnets", compartment_id=oci_tenancy)
        oci_subnet_id = subnets[0].id

    if not OCI_IMAGE_ID:
        images = execute_oci_command(
            compute_client,
            "list_images",
            compartment_id=oci_tenancy,
            shape=OCI_COMPUTE_SHAPE,
        )
        shortened_images = [
            {key: json.loads(str(image))[key] for key in IMAGE_LIST_KEYS} for image in images
        ]
        write_into_file("images_list.json", json.dumps(shortened_images, indent=2))
        oci_image_id = next(
            image.id
            for image in images
            if image.operating_system == OPERATING_SYSTEM
            and image.operating_system_version == OS_VERSION
        )
    else:
        oci_image_id = OCI_IMAGE_ID

    assign_public_ip = ASSIGN_PUBLIC_IP.lower() in ["true", "1", "y", "yes"]
    boot_volume_size = max(50, int(BOOT_VOLUME_SIZE))
    ssh_public_key = read_ssh_public_key(SSH_PUBLIC_KEY_FILE)

    instance_exist_flag = check_instance_state_and_write(oci_tenancy, OCI_COMPUTE_SHAPE, tries=1)

    if OCI_COMPUTE_SHAPE == "VM.Standard.A1.Flex":
        shape_config = oci.core.models.LaunchInstanceShapeConfigDetails(ocpus=4, memory_in_gbs=24)
    else:
        shape_config = oci.core.models.LaunchInstanceShapeConfigDetails(ocpus=1, memory_in_gbs=1)

    while not instance_exist_flag:
        for i, ad in enumerate(oci_ad_name):
            if i > 0:
                print(f"Waiting {AD_WAIT_TIME}s before trying next AD...")
                time.sleep(AD_WAIT_TIME)

            print(f"Trying Availability Domain: {ad}")
            try:
                launch_instance_response = compute_client.launch_instance(
                    launch_instance_details=oci.core.models.LaunchInstanceDetails(
                        availability_domain=ad,
                        compartment_id=oci_tenancy,
                        create_vnic_details=oci.core.models.CreateVnicDetails(
                            assign_public_ip=assign_public_ip,
                            assign_private_dns_record=True,
                            display_name=DISPLAY_NAME,
                            subnet_id=oci_subnet_id,
                        ),
                        display_name=DISPLAY_NAME,
                        shape=OCI_COMPUTE_SHAPE,
                        availability_config=oci.core.models.LaunchInstanceAvailabilityConfigDetails(
                            recovery_action="RESTORE_INSTANCE"
                        ),
                        instance_options=oci.core.models.InstanceOptions(
                            are_legacy_imds_endpoints_disabled=False
                        ),
                        shape_config=shape_config,
                        source_details=oci.core.models.InstanceSourceViaImageDetails(
                            source_type="image",
                            image_id=oci_image_id,
                            boot_volume_size_in_gbs=boot_volume_size,
                        ),
                        metadata={"ssh_authorized_keys": ssh_public_key},
                    )
                )
                if launch_instance_response.status == 200:
                    instance_exist_flag = check_instance_state_and_write(
                        oci_tenancy, OCI_COMPUTE_SHAPE
                    )
                    if instance_exist_flag:
                        break
except oci.exceptions.ServiceError as srv_err:
            if srv_err.status == 429:
                print(f"Rate limited (429). Waiting {RATE_LIMIT_WAIT_TIME}s...")
                time.sleep(RATE_LIMIT_WAIT_TIME)
                continue
            if srv_err.code == "LimitExceeded":
                instance_exist_flag = check_instance_state_and_write(
                    oci_tenancy, OCI_COMPUTE_SHAPE
                )
                if instance_exist_flag:
                    sys.exit()
            data = {
                "status": srv_err.status,
                "code": srv_err.code,
                "message": srv_err.message,
            }
            print(f"Error: {data['code']} - {data['message']}")
            send_telegram_message(
                f"❗️ Error launching instance on {ad}: <code>{data['code']}</code>\n"
                f"Status: {data['status']}\n"
                f"Message: {data['message']}"
            )

        if not instance_exist_flag:
            print(f"All ADs tried. Waiting {WAIT_TIME}s before restarting cycle...")
            time.sleep(WAIT_TIME)


if __name__ == "__main__":
    init_oci_clients()
    send_telegram_message(
        "🚀 <b>OCI Instance Creation Script</b>\n\nStarting up! Attempting to create Oracle Cloud Free Tier ARM instance..."
    )
    try:
        launch_instance()
        send_telegram_message("🎉 <b>Success!</b>\n\nOCI Instance has been created successfully!")
        print("Instance created successfully. Exiting...")
        sys.exit(0)
    except Exception as e:
        error_message = (
            f"😱 <b>Error!</b>\n\nOCI Instance Creation failed:\n\n<code>{str(e)}</code>"
        )
        send_telegram_message(error_message)
        raise
        raise
