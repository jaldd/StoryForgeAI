package ai.storyforge.application.dto;

public class OptimizationResultDto {
    private String documentId;
    private String originalContent;
    private String optimizedContent;
    private String suggestions;
    private boolean hasChanges;

    public OptimizationResultDto() {
    }

    public OptimizationResultDto(String documentId, String originalContent, String optimizedContent, String suggestions, boolean hasChanges) {
        this.documentId = documentId;
        this.originalContent = originalContent;
        this.optimizedContent = optimizedContent;
        this.suggestions = suggestions;
        this.hasChanges = hasChanges;
    }

    public String getDocumentId() {
        return documentId;
    }

    public void setDocumentId(String documentId) {
        this.documentId = documentId;
    }

    public String getOriginalContent() {
        return originalContent;
    }

    public void setOriginalContent(String originalContent) {
        this.originalContent = originalContent;
    }

    public String getOptimizedContent() {
        return optimizedContent;
    }

    public void setOptimizedContent(String optimizedContent) {
        this.optimizedContent = optimizedContent;
    }

    public String getSuggestions() {
        return suggestions;
    }

    public void setSuggestions(String suggestions) {
        this.suggestions = suggestions;
    }

    public boolean isHasChanges() {
        return hasChanges;
    }

    public void setHasChanges(boolean hasChanges) {
        this.hasChanges = hasChanges;
    }
}