sudo kubectl patch app kaanbal-console-prod -n argocd --type merge -p '{\"operation\": {\"sync\": {\"revision\": \"HEAD\"}}}'
