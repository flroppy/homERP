const path = require('path');
const fs = require('fs');

module.exports = function(eleventyConfig) {

  eleventyConfig.addGlobalData("layout", "item.njk");

  // Copy assets to output directory
  eleventyConfig.addPassthroughCopy("house/**")
  
  // Add a filter to get parent folder name as location
  eleventyConfig.addFilter("getParentLocation", function(inputPath) {
    if (!inputPath) return '';
    
    // Get the parent folder path (one level up from the item's folder)
    const itemDirPath = path.dirname(inputPath);
    const parentDirPath = path.dirname(itemDirPath);
    
    // Get just the basename (folder name) of the parent
    const parentFolderName = path.basename(parentDirPath);
    
    // Don't return root as a location
    return parentFolderName === '.' ? '' : parentFolderName;
  });
  
  // Create collections by category
  eleventyConfig.addCollection("categories", function(collectionApi) {
    const categories = {};
    const items = collectionApi.getAll();
    
    items.forEach(item => {
      if (item.data.category) {
        if (!categories[item.data.category]) {
          categories[item.data.category] = [];
        }
        categories[item.data.category].push(item);
      }
    });
    
    return categories;
  });

  // Create a collection for all items
  eleventyConfig.addCollection("allItems", function(collectionApi) {
    return collectionApi.getAll();
  });
  
  // Filter to get attachments for an item
  eleventyConfig.addFilter("getAttachments", function(collection, itemPath) {
    const attachments = [];
    
    try {
      const fullPath = path.join(__dirname, itemPath);
      if (fs.existsSync(fullPath)) {
        const files = fs.readdirSync(fullPath);
        
        files.forEach(file => {
          // Skip directories and index.md
          const stats = fs.statSync(path.join(fullPath, file));
          if (!stats.isDirectory() && file !== "index.md") {
            attachments.push({
              filename: file,
              url: path.join(itemPath, file)
            });
          }
        });
      }
    } catch (err) {
      console.error(`Error getting attachments for ${itemPath}:`, err);
    }
    
    return attachments;
  });
  
  // Filter to get sub-items (folders within the current item)
  eleventyConfig.addFilter("getSubItems", function(collection, parentUrl) {
    return collection.filter(item => {
      // Get parent path without trailing slash
      const parent = parentUrl.endsWith('/') 
        ? parentUrl.slice(0, -1) 
        : parentUrl;
        
      // Get item path and its directory
      const itemPath = item.url;
      const itemDir = path.dirname(itemPath);
      
      // Check if this item is directly under the parent
      // but not the parent itself
      return itemDir === parent && itemPath !== parentUrl;
    });
  });
  
  return {
    dir: {
      input: ".",
      output: "_site",
      includes: "_includes",
      layouts: "_layouts"
    },
    templateFormats: ["md", "njk", "html"],
    markdownTemplateEngine: "njk",
    htmlTemplateEngine: "njk",
    dataTemplateEngine: "njk"
  };
};
