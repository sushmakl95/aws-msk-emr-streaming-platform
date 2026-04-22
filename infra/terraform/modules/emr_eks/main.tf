variable "name_prefix" { type = string }
variable "subnet_ids" { type = list(string) }
variable "vpc_id" { type = string }
variable "kms_key_arn" { type = string }
variable "execution_role_arn" { type = string }
variable "cluster_version" { type = string }

# -----------------------------------------------------------------------------
# EKS cluster (minimal — users will add node groups or use Fargate)
# -----------------------------------------------------------------------------
resource "aws_iam_role" "eks_cluster" {
  name = "${var.name_prefix}-eks-cluster-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "eks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "eks_cluster_policy" {
  role       = aws_iam_role.eks_cluster.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
}

resource "aws_eks_cluster" "this" {
  name     = "${var.name_prefix}-eks"
  role_arn = aws_iam_role.eks_cluster.arn
  version  = var.cluster_version

  vpc_config {
    subnet_ids              = var.subnet_ids
    endpoint_private_access = true
    endpoint_public_access  = false
  }

  encryption_config {
    provider {
      key_arn = var.kms_key_arn
    }
    resources = ["secrets"]
  }

  depends_on = [aws_iam_role_policy_attachment.eks_cluster_policy]
}

# -----------------------------------------------------------------------------
# EMR virtual cluster (points to the EKS cluster)
# -----------------------------------------------------------------------------
resource "aws_emrcontainers_virtual_cluster" "this" {
  name = "${var.name_prefix}-emr-eks-vc"

  container_provider {
    id   = aws_eks_cluster.this.name
    type = "EKS"
    info {
      eks_info {
        namespace = "emr-streaming"
      }
    }
  }
}

output "eks_cluster_name" { value = aws_eks_cluster.this.name }
output "eks_cluster_endpoint" { value = aws_eks_cluster.this.endpoint }
output "virtual_cluster_id" { value = aws_emrcontainers_virtual_cluster.this.id }
